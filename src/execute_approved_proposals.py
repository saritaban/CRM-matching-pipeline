
"""
Execute approved Bellhaven CRM proposals.

Default: DRY RUN (no CRM writes)
Live execution: python -m src.execute_approved_proposals --execute

Execute one proposal:
python -m src.execute_approved_proposals --execute --proposal-id 23
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from src.database import SessionLocal
from src.models import Proposal, ProposalAudit
from src.crm_client import CRMClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

BELHAVEN_PARENT_ID = "0015QAPLGS3FVYEEEM"

# These actions are intentionally not executed as CRM writes.
NO_WRITE_ACTIONS = {
    "LINK_EXISTING",
    "REVIEW_MATCH",
    "REVIEW_CRM_ONLY",
}


# ---------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------

def json_safe(value):
    """Convert Decimal and datetime values into JSON-compatible values."""
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}

    if isinstance(value, list):
        return [json_safe(v) for v in value]

    return value


def parse_amount(value):
    """Convert CRM financial values to Decimal safely."""
    if value is None or value == "":
        return Decimal("0")

    try:
        return Decimal(str(value).replace(",", "").replace("$", ""))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Could not interpret financial value: {value!r}")


def unwrap_data(response):
    """
    Unwrap common API response structures.

    Examples:
      {"data": {...}}
      {"data": [{...}]}
      {...}
    """
    if isinstance(response, dict) and "data" in response:
        return response["data"]

    return response


def extract_account_id(response):
    """
    Extract an account ID from a POST response.

    Deliberately accepts only account_id or id fields.
    If the API response does not expose an ID, reconciliation is required.
    """
    data = unwrap_data(response)

    if isinstance(data, dict):
        account_id = data.get("account_id") or data.get("id")

        if account_id:
            return str(account_id)

    return None


def get_live_account(client, account_id):
    """Fetch one current CRM account."""
    response = client.get(f"/accounts/{account_id}")
    data = unwrap_data(response)

    if isinstance(data, list):
        if len(data) == 1:
            data = data[0]
        else:
            raise ValueError(
                f"Unexpected account response for {account_id}: {response}"
            )

    if not isinstance(data, dict):
        raise ValueError(
            f"Could not read CRM account {account_id}: {response}"
        )

    returned_id = data.get("account_id") or data.get("id")

    if returned_id and str(returned_id) != str(account_id):
        raise ValueError(
            f"CRM returned account {returned_id}, expected {account_id}"
        )

    return data


def add_audit_record(
    db,
    proposal_id,
    action,
    details,
    performed_by="approved_proposal_executor",
):
    """Write an audit record for the proposal execution."""
    audit = ProposalAudit(
        proposal_id=proposal_id,
        action=action,
        performed_by=performed_by,
        details=json_safe(details),
    )

    db.add(audit)


def save_execution_result(
    db,
    proposal,
    result,
    audit_action,
):
    """
    Save execution results without discarding earlier partial results.

    This is important for CHOW: a new account may have been created
    successfully even if updating the old account subsequently fails.
    """
    previous = proposal.execution_result or {}

    merged_result = {
        **previous,
        **json_safe(result),
        "last_updated_at": datetime.now(timezone.utc).isoformat(),
    }

    proposal.execution_result = merged_result

    add_audit_record(
        db=db,
        proposal_id=proposal.id,
        action=audit_action,
        details=merged_result,
    )

    db.commit()

    return merged_result


def claim_proposal(db, proposal):
    """
    Claim a proposal before making an external API call.

    Existing execution results are not automatically retried.
    This prevents duplicate POST requests after an interrupted run.
    """
    db.refresh(proposal, with_for_update=True)

    if proposal.status != "Approved":
        return False, "Proposal is not Approved."

    previous = proposal.execution_result or {}
    previous_state = previous.get("state")

    if previous_state:
        return (
            False,
            f"Proposal already has execution state '{previous_state}'. "
            "Manual review is required before retrying.",
        )

    proposal.execution_result = {
        "state": "STARTED",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    add_audit_record(
        db,
        proposal.id,
        "EXECUTION_STARTED",
        proposal.execution_result,
    )

    db.commit()

    return True, "Claimed."


def mark_no_write(db, proposal, reason):
    """Record an approved proposal that intentionally makes no CRM change."""
    result = {
        "state": "NO_CRM_WRITE_REQUIRED",
        "reason": reason,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    save_execution_result(
        db,
        proposal,
        result,
        "EXECUTION_SKIPPED_NO_WRITE",
    )

    logger.info("Proposal %s: %s", proposal.id, reason)


def fail_proposal(db, proposal, error, state="FAILED"):
    """Record a failure."""
    result = {
        "state": state,
        "error": str(error),
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }

    save_execution_result(
        db,
        proposal,
        result,
        "EXECUTION_FAILED",
    )

    logger.exception("Proposal %s failed: %s", proposal.id, error)


# ---------------------------------------------------------------------
# CRM write helpers
# ---------------------------------------------------------------------


def create_crm_account(client, payload):
    """
    Create an account using only the approved new_account_payload.

    Do not use proposal.crm_account_id for CREATE_ACCOUNT proposals.
    """
    if not isinstance(payload, dict):
        raise ValueError("new_account_payload is missing or invalid.")

    name = payload.get("name")

    if not name:
        raise ValueError("New account payload must contain a name.")

    if payload.get("parent_id") != BELHAVEN_PARENT_ID:
        raise ValueError(
            "New account parent_id is not the expected Bellhaven parent."
        )

    logger.info("Creating CRM account: %s", name)

    try:
        response = client.post("/accounts", payload)

    except requests.RequestException as exc:
        logger.exception(
            "POST request failed for %s. CRM creation outcome may be uncertain.",
            name,
        )
        raise RuntimeError(
            f"CRM creation outcome is uncertain for {name}. "
            "Check the CRM before attempting another POST."
        ) from exc

    new_account_id = extract_account_id(response)

    if not new_account_id:
        logger.error(
            "CRM POST returned without a recognizable account ID: %s",
            json_safe(response),
        )

    return new_account_id, response

def patch_crm_account(client, account_id, patch_payload):
    """PATCH an existing CRM account."""
    if not isinstance(patch_payload, dict) or not patch_payload:
        raise ValueError("PATCH payload is empty or invalid.")

    logger.info(
        "Updating CRM account %s with %s",
        account_id,
        patch_payload,
    )

    return client.patch(
        f"/accounts/{account_id}",
        patch_payload,
    )


def verify_account_fields(client, account_id, expected_fields):
    """Re-fetch the account and verify the requested fields."""
    actual = get_live_account(client, account_id)

    mismatches = {}

    for field, expected in expected_fields.items():
        actual_value = actual.get(field)

        if str(actual_value or "") != str(expected or ""):
            mismatches[field] = {
                "expected": expected,
                "actual": actual_value,
            }

    if mismatches:
        raise ValueError(
            f"CRM verification failed for {account_id}: {mismatches}"
        )

    return actual


# ---------------------------------------------------------------------
# Financial safeguards
# ---------------------------------------------------------------------

def has_revenue_and_ar(account):
    revenue = parse_amount(account.get("lifetime_revenue"))
    outstanding_ar = parse_amount(account.get("outstanding_ar"))

    return revenue > 0 and outstanding_ar > 0


def validate_chow_rule(client, old_account_id):
    """
    CHOW is permitted only when the current CRM account has BOTH
    lifetime_revenue > 0 and outstanding_ar > 0.
    """
    live_account = get_live_account(client, old_account_id)

    if not has_revenue_and_ar(live_account):
        raise ValueError(
            "CHOW safeguard failed: the latest CRM account does not have "
            "both lifetime_revenue > 0 and outstanding_ar > 0. "
            "No account was created."
        )

    return live_account


def validate_reparent_rule(client, account_id):
    """
    Direct re-parenting is permitted only when the account does NOT
    have both lifetime_revenue > 0 and outstanding_ar > 0.
    """
    live_account = get_live_account(client, account_id)

    if has_revenue_and_ar(live_account):
        raise ValueError(
            "Re-parent safeguard failed: the latest CRM account now has "
            "both lifetime_revenue > 0 and outstanding_ar > 0. "
            "No PATCH was performed."
        )

    return live_account


# ---------------------------------------------------------------------
# Proposal execution functions
# ---------------------------------------------------------------------


def execute_create_account(db, client, proposal, changes):
    payload = changes.get("new_account_payload")

    if not payload:
        raise ValueError("CREATE_ACCOUNT has no new_account_payload.")

    # Do not use proposal.crm_account_id for this action.
    new_account_id, response = create_crm_account(client, payload)

    if not new_account_id:
        save_execution_result(
            db,
            proposal,
            {
                "state": "FAILED_NEEDS_RECONCILIATION",
                "reason": "POST response did not expose an account ID. "
                          "Check the CRM before retrying.",
                "create_response": json_safe(response),
                "submitted_payload": json_safe(payload),
            },
            "ACCOUNT_CREATED_ID_NOT_CONFIRMED",
        )
        return

    # Record the ID before verification so a later failure cannot
    # cause an accidental second POST.
    save_execution_result(
        db,
        proposal,
        {
            "state": "NEW_ACCOUNT_CREATED",
            "created_account_id": new_account_id,
            "create_response": json_safe(response),
        },
        "ACCOUNT_CREATED",
    )

    expected = {
        key: value
        for key, value in payload.items()
        if key in {
        "name",
        "parent_id",
        "billing_street",
        "billing_city",
        "billing_state",
        "billing_zip",
        }
    }

    verify_account_fields(client, new_account_id, expected)

    verify_account_fields(client, new_account_id, expected)

    save_execution_result(
        db,
        proposal,
        {
            "state": "SUCCESS",
            "created_account_id": new_account_id,
            "created_account_name": payload["name"],
            "verified_fields": expected,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
        "CREATE_ACCOUNT_SUCCESS",
    )

    logger.info(
        "Proposal %s: created and verified account %s",
        proposal.id,
        new_account_id,
    )

def execute_chow(db, client, proposal, changes):
    old_account_id = changes.get("account_id") or proposal.crm_account_id

    if not old_account_id:
        raise ValueError("CHOW proposal has no old account ID.")

    payload = changes.get("new_account_payload")

    if not payload:
        raise ValueError("CHOW proposal has no new_account_payload.")

    # If a prior attempt already created an account, do not POST again.
    previous = proposal.execution_result or {}
    existing_new_id = previous.get("created_account_id")

    if existing_new_id:
        raise ValueError(
            "A new account ID is already recorded for this CHOW proposal: "
            f"{existing_new_id}. Manual reconciliation is required; "
            "the executor will not create another account."
        )

    # Fetch latest CRM values and enforce the CHOW rule.
    old_account = validate_chow_rule(client, old_account_id)

    # Ensure the old account is still the account expected by the proposal.
    expected_old_parent = changes.get("old_parent_id")

    if (
        expected_old_parent
        and str(old_account.get("parent_id") or "")
        != str(expected_old_parent)
    ):
        raise ValueError(
            "The old account's parent has changed since proposal approval. "
            "Manual review is required."
        )

    # Step 1: create the new account.
    new_account_id, create_response = create_crm_account(client, payload)

    if not new_account_id:
        save_execution_result(
            db,
            proposal,
            {
                "state": "FAILED_NEEDS_RECONCILIATION",
                "reason": (
                    "CHOW POST response did not expose an account ID. "
                    "Check the CRM before retrying."
                ),
                "create_response": json_safe(create_response),
                "old_account_id": old_account_id,
                "submitted_payload": json_safe(payload),
            },
            "CHOW_CREATE_ID_NOT_CONFIRMED",
        )
        return

    # Save the new account ID immediately before attempting the old
    # account PATCH. If PATCH fails, the ID is preserved.
    save_execution_result(
        db,
        proposal,
        {
            "state": "NEW_ACCOUNT_CREATED",
            "created_account_id": new_account_id,
            "old_account_id": old_account_id,
            "create_response": json_safe(create_response),
        },
        "CHOW_NEW_ACCOUNT_CREATED",
    )

    try:
        # Verify the new account before linking the old account to it.
        verify_account_fields(
            client,
            new_account_id,
            {
                "name": payload["name"],
                "parent_id": payload["parent_id"],
            },
        )

        # Step 2: update only chow_current_account on the old account.
        # Do NOT change its parent.
        old_patch = {
            "chow_current_account": new_account_id,
        }

        patch_response = patch_crm_account(
            client,
            old_account_id,
            old_patch,
        )

        verify_account_fields(
            client,
            old_account_id,
            old_patch,
        )

        save_execution_result(
            db,
            proposal,
            {
                "state": "SUCCESS",
                "created_account_id": new_account_id,
                "old_account_id": old_account_id,
                "old_account_patch": old_patch,
                "patch_response": json_safe(patch_response),
                "old_account_parent_preserved": True,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            "CHOW_SUCCESS",
        )

        logger.info(
            "Proposal %s: CHOW completed. New account: %s",
            proposal.id,
            new_account_id,
        )

    except Exception as exc:
        # Preserve the created account ID. Never retry the POST blindly.
        save_execution_result(
            db,
            proposal,
            {
                "state": "FAILED_NEEDS_RECONCILIATION",
                "created_account_id": new_account_id,
                "old_account_id": old_account_id,
                "error": str(exc),
                "reason": (
                    "New account was created, but the old account update "
                    "or verification did not complete. Check both CRM "
                    "accounts before taking further action."
                ),
            },
            "CHOW_REQUIRES_RECONCILIATION",
        )

        logger.exception(
            "Proposal %s: new account created, but CHOW needs reconciliation.",
            proposal.id,
        )


def execute_reparent(db, client, proposal, changes):
    account_id = changes.get("account_id") or proposal.crm_account_id

    if not account_id:
        raise ValueError("REPARENT proposal has no CRM account ID.")

    patch_payload = changes.get("existing_account_patch")

    if not patch_payload:
        raise ValueError("REPARENT proposal has no existing_account_patch.")

    # Re-check financial values immediately before the PATCH.
    live_account = validate_reparent_rule(client, account_id)

    expected_old_parent = changes.get("old_parent_id")

    if (
        expected_old_parent
        and str(live_account.get("parent_id") or "")
        != str(expected_old_parent)
    ):
        raise ValueError(
            "The account's parent has changed since proposal approval. "
            "Manual review is required."
        )

    patch_response = patch_crm_account(
        client,
        account_id,
        patch_payload,
    )

    verify_account_fields(
        client,
        account_id,
        patch_payload,
    )

    save_execution_result(
        db,
        proposal,
        {
            "state": "SUCCESS",
            "account_id": account_id,
            "patch_payload": patch_payload,
            "patch_response": json_safe(patch_response),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
        "REPARENT_SUCCESS",
    )

    logger.info(
        "Proposal %s: account %s re-parented and verified.",
        proposal.id,
        account_id,
    )


# ---------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------

def execute_proposal(db, client, proposal, execute_live):
    changes = proposal.recommended_changes or {}
    action = proposal.action_type

    logger.info(
        "Proposal %s | %s | %s",
        proposal.id,
        action,
        proposal.status,
    )

    if proposal.status != "Approved":
        logger.info("Skipping proposal %s: not approved.", proposal.id)
        return






    if not execute_live:
        logger.info(
        "[DRY RUN] Proposal %s | Action: %s | Changes: %s",
        proposal.id,
        action,
        json.dumps(json_safe(changes), indent=2),
        )
        return





    # No-write actions are never sent to the CRM.
    if action == "LINK_EXISTING":
        mark_no_write(
            db,
            proposal,
            "Existing CRM account was approved as the match; no CRM write is required.",
        )
        return

    if action == "REVIEW_MATCH":
        mark_no_write(
            db,
            proposal,
            "Manual review was approved, but automatic_update is false. "
            "No CRM change is authorized by this proposal.",
        )
        return

    if action == "REVIEW_CRM_ONLY":
        mark_no_write(
            db,
            proposal,
            "CRM-only account review does not authorize a CRM update.",
        )
        return

    supported_actions = {
        "CREATE_ACCOUNT",
        "CHOW_CREATE_NEW_ACCOUNT",
        "REPARENT_EXISTING_ACCOUNT",
    }

    if action not in supported_actions:
        logger.warning(
            "Proposal %s has unsupported action %s. Skipping.",
            proposal.id,
            action,
        )
        return

    if not execute_live:
        logger.info(
            "[DRY RUN] Proposal %s would execute action %s.",
            proposal.id,
            action,
        )
        logger.info(
            "[DRY RUN] Recommended changes: %s",
            json.dumps(json_safe(changes), indent=2),
        )
        return

    claimed, message = claim_proposal(db, proposal)

    if not claimed:
        logger.warning(
            "Proposal %s was not executed: %s",
            proposal.id,
            message,
        )
        return

    try:
        if action == "CREATE_ACCOUNT":
            execute_create_account(db, client, proposal, changes)

        elif action == "CHOW_CREATE_NEW_ACCOUNT":
            execute_chow(db, client, proposal, changes)

        elif action == "REPARENT_EXISTING_ACCOUNT":
            execute_reparent(db, client, proposal, changes)

    except Exception as exc:
        db.rollback()

        # Reload the proposal after rollback before recording the failure.
        db.refresh(proposal)

        previous = proposal.execution_result or {}

        # If an external account may already have been created, do not
        # classify this as an ordinary retryable failure.
        if previous.get("created_account_id"):
            fail_proposal(
                db,
                proposal,
                exc,
                state="FAILED_NEEDS_RECONCILIATION",
            )
        else:
            fail_proposal(
                db,
                proposal,
                exc,
                state="FAILED",
            )


def main():
    parser = argparse.ArgumentParser(
        description="Execute approved Bellhaven CRM proposals."
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform live CRM updates. Without this flag, only dry-run.",
    )

    parser.add_argument(
        "--proposal-id",
        type=int,
        help="Execute or preview one proposal by ID.",
    )

    args = parser.parse_args()

    db = SessionLocal()
    client = CRMClient()

    try:
        query = db.query(Proposal).filter(
            Proposal.status == "Approved"
        )

        if args.proposal_id is not None:
            query = query.filter(
                Proposal.id == args.proposal_id
            )

        proposals = query.order_by(Proposal.id).all()

        if not proposals:
            logger.info("No approved proposals found.")
            return

        mode = "LIVE EXECUTION" if args.execute else "DRY RUN"

        logger.info("=" * 70)
        logger.info("MODE: %s", mode)
        logger.info("Approved proposals found: %s", len(proposals))
        logger.info("=" * 70)

        if args.execute:
            logger.warning(
                "LIVE CRM WRITES ARE ENABLED. Only supported approved "
                "actions will be sent to the CRM."
            )

        for proposal in proposals:
            execute_proposal(
                db=db,
                client=client,
                proposal=proposal,
                execute_live=args.execute,
            )

        logger.info("=" * 70)
        logger.info("Execution process finished.")
        logger.info("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    main()
