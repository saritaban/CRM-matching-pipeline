
from decimal import Decimal

BELLHAVEN_PARENT_ID = "0015QAPLGS3FVYEEEM"


def money(value):
    return Decimal(str(value or 0))

def determine_parent_action(account):
    revenue = money(account.get("lifetime_revenue"))
    outstanding_ar = money(account.get("outstanding_ar"))

    if revenue > 0 and outstanding_ar > 0:
        return {
            "action": "CHOW_CREATE_NEW_ACCOUNT",
            "create_new_account": True,
            "update_old_parent": False,
            "update_old_chow": True,
            "reason": (
                "Account has both lifetime revenue and outstanding AR. "
                "Preserve the existing account and create a new account "
                "under Bellhaven."
            ),
        }

    return {
        "action": "REPARENT_EXISTING_ACCOUNT",
        "create_new_account": False,
        "update_old_parent": True,
        "update_old_chow": False,
        "reason": (
            "The account does not have both lifetime revenue and "
            "outstanding AR greater than zero. The existing account "
            "can be re-parented."
        ),
    }


def classify_wrong_parent(account, website):
    decision = determine_parent_action(account)

    old_name = account.get("name")
    new_name = website.get("name")

    # CHOW: create a separate account.
    if decision["create_new_account"]:
        new_account_payload = {
            "name": new_name,
            "parent_id": BELLHAVEN_PARENT_ID,
            "billing_street": website.get("street"),
            "billing_city": website.get("city"),
            "billing_state": website.get("state"),
            "billing_zip": website.get("zip"),
        }

        return {
            **decision,
            "account_id": account.get("account_id"),
            "old_name": old_name,
            "new_name": new_name,
            "old_parent_id": account.get("parent_id"),
            "new_parent_id": BELLHAVEN_PARENT_ID,
            "new_account_payload": new_account_payload,
            # The new account ID is not known until creation succeeds.
            "old_account_patch_template": {
                "chow_current_account": "NEW_ACCOUNT_ID_REQUIRED"
            },
            "status": "Pending",
        }

    # Direct re-parent: update the existing account only.
    existing_account_patch = {
        "parent_id": BELLHAVEN_PARENT_ID
    }

    if old_name and new_name and old_name != new_name:
        existing_account_patch["name"] = new_name

    return {
        **decision,
        "account_id": account.get("account_id"),
        "old_name": old_name,
        "new_name": new_name,
        "old_parent_id": account.get("parent_id"),
        "new_parent_id": BELLHAVEN_PARENT_ID,
        "existing_account_patch": existing_account_patch,
        "status": "Pending",
    }


def classify_crm_only(account):
    return {
        "action": "REVIEW_CRM_ONLY",
        "account_id": account.get("account_id"),
        "account_name": account.get("name"),
        "current_status": account.get("status"),
        "proposed_status": "Needs Review",
        "proposed_note": (
            "Account was not found in the current Bellhaven website "
            "community listing. Review facility status before deactivation."
        ),
        "reason": (
            "Website absence alone does not prove that the facility "
            "is closed or should be deactivated."
        ),
        "status": "Pending",
    }


def classify_new_location(website):
    return {
        "action": "CREATE_ACCOUNT",
        "website_name": website.get("name"),
        "new_account_payload": {
            "name": website.get("name"),
            "parent_id": BELLHAVEN_PARENT_ID,
            "billing_street": website.get("street"),
            "billing_city": website.get("city"),
            "billing_state": website.get("state"),
            "billing_zip": website.get("zip"),
        },
        "status": "Pending",
    }
