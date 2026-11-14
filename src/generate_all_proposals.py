
import json
from decimal import Decimal
from pathlib import Path

from src.database import SessionLocal
from src.models import WebsiteLocation, CRMAccount, Proposal
from src.business_rules import (
    BELLHAVEN_PARENT_ID,
    classify_wrong_parent,
    classify_new_location,
    classify_crm_only,
)


CLASSIFICATION_FILE = Path("data/classification_results.json")


def json_safe(value):
    """Convert values into JSON-compatible objects."""
    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}

    if isinstance(value, list):
        return [json_safe(v) for v in value]

    return value


def get_crm_account_data(account):
    """Build an account dictionary using ORM fields and raw API data."""

    data = dict(account.raw_data or {})

    # Use current database fields as authoritative values.
    data.update({
        "account_id": account.account_id,
        "name": account.account_name,
        "parent_id": account.parent_account_id,
        "street": account.street,
        "city": account.city,
        "state": account.state,
        "zip": account.zip,
    })

    return data


def get_website_data(result):
    """Convert classification website fields into business-rule format."""

    address = result.get("website_address", {})

    return {
        "name": result.get("website_name"),
        "street": address.get("street"),
        "city": address.get("city"),
        "state": address.get("state"),
        "zip": address.get("zip"),
    }


def get_confidence_score(result):
    candidate = result.get("best_candidate") or {}

    score = candidate.get("score")

    return Decimal(str(score)) if score is not None else None



def find_existing_proposals(
    db,
    website_location_id=None,
    crm_account_id=None,
):
    """
    Find all proposals for the same business identity.

    Website identity: website_location_id
    CRM-only identity: crm_account_id when website_location_id is None

    Deliberately does not filter by action_type or candidate CRM account
    for website locations.
    """

    query = db.query(Proposal)

    if website_location_id is not None:
        query = query.filter(
            Proposal.website_location_id == website_location_id
        )

    elif crm_account_id is not None:
        query = query.filter(
            Proposal.website_location_id.is_(None),
            Proposal.crm_account_id == crm_account_id,
        )

    else:
        raise ValueError(
            "A proposal must have a website location ID "
            "or a CRM account ID."
        )

    return query.order_by(Proposal.id.desc()).all()
def save_proposal(
    db,
    website_location_id,
    crm_account_id,
    action_type,
    confidence_score,
    evidence,
    recommended_changes,
):
    """
    Safely create or update a proposal.

    Rules:
    1. Never overwrite Approved or Rejected decisions.
    2. A reviewed website location cannot receive another proposal
       automatically, even if its candidate or action changes.
    3. CRM-only decisions are protected by CRM account ID.
    4. Update an existing Pending proposal instead of creating duplicates.
    5. Stop if multiple Pending proposals already exist for the same identity.
    """

    existing = find_existing_proposals(
        db=db,
        website_location_id=website_location_id,
        crm_account_id=crm_account_id,
    )

    # Preserve reviewed decisions regardless of action type.
    reviewed = [
        proposal
        for proposal in existing
        if proposal.status in ("Approved", "Rejected")
    ]

    if reviewed:
        print(
            f"Skipping reviewed decision: "
            f"website_location_id={website_location_id}, "
            f"crm_account_id={crm_account_id}, "
            f"reviewed_proposal_ids={[p.id for p in reviewed]}"
        )
        return "skipped"

    # Find all pending proposals for this business identity.
    pending_proposals = [
        proposal
        for proposal in existing
        if proposal.status == "Pending"
    ]

    # Do not silently leave multiple actionable proposals.
    if len(pending_proposals) > 1:
        proposal_ids = [p.id for p in pending_proposals]

        raise RuntimeError(
            "Multiple Pending proposals found for the same business "
            f"identity. Manual cleanup required. IDs: {proposal_ids}"
        )

    # Update the one existing Pending proposal.
    if pending_proposals:
        pending = pending_proposals[0]

        pending.crm_account_id = crm_account_id
        pending.action_type = action_type
        pending.confidence_score = confidence_score
        pending.evidence = json_safe(evidence)
        pending.recommended_changes = json_safe(recommended_changes)

        print(f"Updated existing Pending proposal: {pending.id}")

        return "updated"

    # No previous proposal exists. Create a new one.
    proposal = Proposal(
        website_location_id=website_location_id,
        crm_account_id=crm_account_id,
        action_type=action_type,
        confidence_score=confidence_score,
        evidence=json_safe(evidence),
        recommended_changes=json_safe(recommended_changes),
        status="Pending",
    )

    db.add(proposal)

    return "created"

def generate_proposals():

    if not CLASSIFICATION_FILE.exists():
        raise FileNotFoundError(
            f"Classification file not found: {CLASSIFICATION_FILE}"
        )

    with open(CLASSIFICATION_FILE, "r", encoding="utf-8") as file:
        classification_data = json.load(file)

    website_results = classification_data["website_results"]
    crm_only_accounts = classification_data["crm_only_accounts"]

    db = SessionLocal()

    created = 0
    updated = 0
    skipped = 0

    try:
        website_records = db.query(WebsiteLocation).all()
        crm_records = db.query(CRMAccount).all()

        website_by_url = {
            record.source_url: record
            for record in website_records
        }

        crm_by_id = {
            record.account_id: record
            for record in crm_records
        }

        print("\nStarting proposal generation")
        print("--------------------------------")
        print("Website classification records:", len(website_results))
        print("Website database records:", len(website_records))
        print("CRM-only accounts:", len(crm_only_accounts))
        print("CRM database records:", len(crm_records))

        # ------------------------------------------------
        # 1. Process all website locations
        # ------------------------------------------------

        for result in website_results:

            website_name = result["website_name"]
            source_url = result["source_url"]
            classification = result["classification"]

            website_record = website_by_url.get(source_url)

            if not website_record:
                raise ValueError(
                    f"Website record not found in database: {source_url}"
                )

            website_data = get_website_data(result)

            best_candidate = result.get("best_candidate") or {}

            crm_account_id = best_candidate.get("account_id")

            crm_account = crm_by_id.get(crm_account_id)

            score = get_confidence_score(result)

            evidence = {
                "classification": classification,
                "website": website_data,
                "source_url": source_url,
                "best_candidate": best_candidate,
                "other_candidates": result.get("other_candidates", []),
                "classification_summary": classification_data.get(
                    "website_classification_summary", {}
                ),
            }

            recommended_changes = {}

            # --------------------------------------------
            # CONFIDENT MATCH
            # --------------------------------------------

            if classification == "CONFIDENT_MATCH":

                if not crm_account:
                    raise ValueError(
                        f"CRM account missing for confident match: "
                        f"{website_name} / {crm_account_id}"
                    )

                if crm_account.parent_account_id != BELLHAVEN_PARENT_ID:
                    action_type = "MANUAL_REVIEW"

                    recommended_changes = {
                        "action": "MANUAL_REVIEW",
                        "reason": (
                            "Confident match candidate is not under "
                            "the Bellhaven parent. Verify before updating."
                        ),
                        "crm_account_id": crm_account_id,
                    }

                else:
                    action_type = "LINK_EXISTING"

                    recommended_changes = {
                        "action": "LINK_EXISTING",
                        "crm_account_id": crm_account_id,
                        "no_crm_update_required": True,
                        "reason": (
                            "Website location matches an existing "
                            "CRM account under the Bellhaven parent."
                        ),
                    }

            # --------------------------------------------
            # WRONG PARENT
            # --------------------------------------------

            elif classification == "MATCH_WRONG_PARENT":

                if not crm_account:
                    raise ValueError(
                        f"CRM account missing for wrong-parent match: "
                        f"{website_name} / {crm_account_id}"
                    )

                account_data = get_crm_account_data(crm_account)

                decision = classify_wrong_parent(
                    account_data,
                    website_data
                )

                action_type = decision["action"]

                recommended_changes = decision

                # Keep care offerings as evidence for reviewer.
                recommended_changes["website_care_offerings"] = (
                    website_record.care_offerings
                )

            # --------------------------------------------
            # NEW WEBSITE LOCATION
            # --------------------------------------------

            elif classification == "NO_CRM_ACCOUNT":

                action_type = "CREATE_ACCOUNT"

                recommended_changes = classify_new_location(
                    website_data
                )

                recommended_changes["website_care_offerings"] = (
                    website_record.care_offerings
                )

                recommended_changes["reason"] = (
                    "No sufficiently credible existing CRM account "
                    "was found. Reviewer approval is required before "
                    "creating a new account."
                )

            # --------------------------------------------
            # POSSIBLE MATCH
            # --------------------------------------------

            elif classification == "POSSIBLE_MATCH":

                action_type = "REVIEW_MATCH"

                recommended_changes = {
                    "action": "REVIEW_MATCH",
                    "crm_account_id": crm_account_id,
                    "reason": (
                        "A possible CRM match was identified, but "
                        "the available evidence is insufficient "
                        "for automatic linking or updating."
                    ),
                    "automatic_update": False,
                }

            else:

                action_type = "MANUAL_REVIEW"

                recommended_changes = {
                    "action": "MANUAL_REVIEW",
                    "reason": (
                        f"Unrecognized classification: {classification}"
                    ),
                }

            result_status = save_proposal(
                db=db,
                website_location_id=website_record.id,
                crm_account_id=crm_account_id,
                action_type=action_type,
                confidence_score=score,
                evidence=evidence,
                recommended_changes=recommended_changes,
            )

            if result_status == "created":
                created += 1
            elif result_status == "updated":
                updated += 1
            else:
                skipped += 1

        # ------------------------------------------------
        # 2. Process CRM-only accounts
        # ------------------------------------------------

        for crm_only in crm_only_accounts:

            account_id = crm_only["account_id"]

            crm_account = crm_by_id.get(account_id)

            if not crm_account:
                raise ValueError(
                    f"CRM-only account not found in database: {account_id}"
                )

            account_data = get_crm_account_data(crm_account)

            decision = classify_crm_only({
                **account_data,
                "status": crm_only.get("status"),
                "lifetime_revenue": crm_only.get("lifetime_revenue"),
                "outstanding_ar": crm_only.get("outstanding_ar"),
            })

            evidence = {
                "classification": "CRM_ONLY",
                "crm_account": crm_only,
                "reason": decision["reason"],
            }

            result_status = save_proposal(
                db=db,
                website_location_id=None,
                crm_account_id=account_id,
                action_type="REVIEW_CRM_ONLY",
                confidence_score=None,
                evidence=evidence,
                recommended_changes=decision,
            )

            if result_status == "created":
                created += 1
            elif result_status == "updated":
                updated += 1
            else:
                skipped += 1

        db.commit()

        print("\nProposal generation completed")
        print("--------------------------------")
        print("New proposals:", created)
        print("Updated pending proposals:", updated)
        print("Preserved reviewed proposals:", skipped)

        print(
            "Total proposals:",
            db.query(Proposal).count()
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    generate_proposals()
