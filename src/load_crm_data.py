
import json
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from src.database import engine
from src.models import CRMAccount
from src.crm_client import CRMClient

BASE_DIR = Path(__file__).resolve().parent.parent
JSON_FILE = BASE_DIR / "data" / "crm_accounts.json"

PAGE_SIZE = 50


def fetch_all_accounts(client):
    all_accounts = []
    page = 1
    expected_total = None

    while True:
        response = client.get(
            "/accounts",
            params={"page": page, "page_size": PAGE_SIZE}
        )

        if not isinstance(response, dict) or "data" not in response:
            raise ValueError(f"Invalid API response on page {page}.")

        accounts = response["data"]

        if not isinstance(accounts, list):
            raise ValueError(f"Invalid account list on page {page}.")

        total = response.get("total")

        if total is None:
            raise ValueError("API response is missing total count.")

        if expected_total is None:
            expected_total = int(total)
        elif int(total) != expected_total:
            raise ValueError("CRM total changed during pagination. Retry refresh.")

        all_accounts.extend(accounts)

        print(
            f"Fetched page {page}: {len(accounts)} accounts "
            f"({len(all_accounts)}/{expected_total})"
        )

        if len(all_accounts) >= expected_total:
            break

        if not accounts:
            raise ValueError("Empty page received before all accounts were fetched.")

        page += 1

    # Validate complete and unique account IDs
    account_ids = [
        str(account.get("account_id"))
        for account in all_accounts
        if account.get("account_id")
    ]

    if len(account_ids) != expected_total:
        raise ValueError(
            f"Expected {expected_total} valid accounts, got {len(account_ids)}."
        )

    if len(set(account_ids)) != len(account_ids):
        raise ValueError("Duplicate account IDs detected across API pages.")

    return {
        "data": all_accounts,
        "page": 1,
        "page_size": PAGE_SIZE,
        "total": expected_total
    }


def load_crm_data():
    client = CRMClient()

    # Fetch every page before modifying local data
    response = fetch_all_accounts(client)
    accounts = response["data"]

    print(f"\nTotal CRM accounts fetched: {len(accounts)}")

    records = []

    for account in accounts:
        account_id = account.get("account_id")

        records.append({
            "account_id": str(account_id),
            "account_name": account.get("name"),
            "parent_account_id": account.get("parent_id"),
            "street": account.get("billing_street"),
            "city": account.get("billing_city"),
            "state": account.get("billing_state"),
            "zip": account.get("billing_zip"),
            "lifetime_revenue": account.get("lifetime_revenue"),
            "outstanding_ar": account.get("outstanding_ar"),
            "chow_current_account": account.get("chow_current_account") or None,
            "duplicate_of_account": account.get("duplicate_of_account") or None,
            "status": account.get("status"),
            "raw_data": account
        })

    # Update local CRM snapshot
    statement = insert(CRMAccount).values(records)

    statement = statement.on_conflict_do_update(
        index_elements=["account_id"],
        set_={
            "account_name": statement.excluded.account_name,
            "parent_account_id": statement.excluded.parent_account_id,
            "street": statement.excluded.street,
            "city": statement.excluded.city,
            "state": statement.excluded.state,
            "zip": statement.excluded.zip,
            "lifetime_revenue": statement.excluded.lifetime_revenue,
            "outstanding_ar": statement.excluded.outstanding_ar,
            "chow_current_account": statement.excluded.chow_current_account,
            "duplicate_of_account": statement.excluded.duplicate_of_account,
            "status": statement.excluded.status,
            "raw_data": statement.excluded.raw_data
        }
    )

    # Save JSON snapshot and database changes
    with engine.begin() as connection:
        connection.execute(statement)

    JSON_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(JSON_FILE, "w", encoding="utf-8") as file:
        json.dump(response, file, indent=4, ensure_ascii=False)

    print(f"Successfully imported {len(records)} CRM accounts.")


if __name__ == "__main__":
    load_crm_data()
