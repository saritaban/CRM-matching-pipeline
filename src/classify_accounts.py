
import json
from pathlib import Path

from rapidfuzz import fuzz

from src.database import SessionLocal
from src.models import WebsiteLocation, CRMAccount
from src.normalize import (
    normalize_company_name,
    normalize_street,
    normalize_city,
    normalize_state,
    normalize_zip,
)


BELLHAVEN_PARENT_ID = "0015QAPLGS3FVYEEEM"

OUTPUT_FILE = Path("data/classification_results.json")

HIGH_CONFIDENCE_THRESHOLD = 90
POSSIBLE_MATCH_THRESHOLD = 75


def get_value(obj, field, default=None):
    """Read a field from the ORM object, falling back to raw CRM data."""
    value = getattr(obj, field, None)

    if value is not None:
        return value

    raw_data = getattr(obj, "raw_data", None) or {}
    return raw_data.get(field, default)


def compare_records(website, crm):
    """Calculate a matching score and supporting address evidence."""

    website_name = normalize_company_name(website.name or "")
    crm_name = normalize_company_name(
        get_value(crm, "account_name", "") or ""
    )

    website_street = normalize_street(website.street or "")
    crm_street = normalize_street(
        get_value(crm, "street", "") or ""
    )

    website_city = normalize_city(website.city or "")
    crm_city = normalize_city(get_value(crm, "city", "") or "")

    website_state = normalize_state(website.state or "")
    crm_state = normalize_state(get_value(crm, "state", "") or "")

    website_zip = normalize_zip(website.zip or "")
    crm_zip = normalize_zip(get_value(crm, "zip", "") or "")

    name_score = (
        fuzz.token_sort_ratio(website_name, crm_name)
        if website_name and crm_name else 0
    )

    street_score = (
        fuzz.token_sort_ratio(website_street, crm_street)
        if website_street and crm_street else 0
    )

    city_match = bool(website_city and crm_city and website_city == crm_city)
    state_match = bool(
        website_state and crm_state and website_state == crm_state
    )
    zip_match = bool(website_zip and crm_zip and website_zip == crm_zip)

    street_match = street_score >= 90

    address_evidence = {
        "street_match": street_match,
        "city_match": city_match,
        "state_match": state_match,
        "zip_match": zip_match,
    }

    address_match_count = sum(address_evidence.values())

    total_score = (
        name_score * 0.40
        + street_score * 0.30
        + (100 if city_match else 0) * 0.10
        + (100 if state_match else 0) * 0.10
        + (100 if zip_match else 0) * 0.10
    )

    return {
        "score": round(total_score, 2),
        "name_score": round(name_score, 2),
        "street_score": round(street_score, 2),
        "address_match_count": address_match_count,
        "address_evidence": address_evidence,
    }


def classify_website_locations(website_locations, crm_accounts):
    """Find the best CRM candidate for each website location."""

    results = []
    recognized_crm_ids = set()

    for website in website_locations:
        candidates = []

        for crm in crm_accounts:
            comparison = compare_records(website, crm)

            candidates.append({
                "account_id": crm.account_id,
                "account_name": get_value(crm, "account_name", ""),
                "parent_account_id": get_value(
                    crm, "parent_account_id", ""
                ),
                **comparison,
            })

        candidates.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        best = candidates[0] if candidates else None

        if best:
            # Recognize credible candidates, not only the top candidate.
            # This prevents possible duplicates from being falsely labelled
            # as CRM-only accounts.
            for candidate in candidates:
                if (
                    candidate["score"] >= POSSIBLE_MATCH_THRESHOLD
                    and candidate["address_match_count"] >= 2
                ):
                    recognized_crm_ids.add(candidate["account_id"])

        if best and (
            best["score"] >= POSSIBLE_MATCH_THRESHOLD
            and best["address_match_count"] >= 2
        ):
            if best["score"] >= HIGH_CONFIDENCE_THRESHOLD:
                classification = "CONFIDENT_MATCH"
            else:
                classification = "POSSIBLE_MATCH"

            if best["parent_account_id"] != BELLHAVEN_PARENT_ID:
                classification = "MATCH_WRONG_PARENT"

        else:
            classification = "NO_CRM_ACCOUNT"

        results.append({
            "website_location_id": website.id,
            "website_name": website.name,
            "website_address": {
                "street": website.street,
                "city": website.city,
                "state": website.state,
                "zip": website.zip,
            },
            "source_url": website.source_url,
            "classification": classification,
            "best_candidate": best,
            "other_candidates": candidates[1:3],
        })

    return results, recognized_crm_ids


def find_crm_only_accounts(crm_accounts, recognized_crm_ids):
    """Find Bellhaven child accounts not represented on the website."""

    results = []

    for crm in crm_accounts:
        parent_id = get_value(crm, "parent_account_id", "")

        if parent_id != BELLHAVEN_PARENT_ID:
            continue

        if crm.account_id in recognized_crm_ids:
            continue

        results.append({
            "account_id": crm.account_id,
            "account_name": get_value(crm, "account_name", ""),
            "parent_account_id": parent_id,
            "status": get_value(crm, "status", ""),
            "lifetime_revenue": get_value(crm, "lifetime_revenue", 0),
            "outstanding_ar": get_value(crm, "outstanding_ar", 0),
            "note": get_value(crm, "note", ""),
            "classification": "CRM_ONLY",
        })

    return results


def main():
    session = SessionLocal()

    try:
        website_locations = session.query(WebsiteLocation).all()
        crm_accounts = session.query(CRMAccount).all()

        print(f"Website locations: {len(website_locations)}")
        print(f"CRM accounts: {len(crm_accounts)}")
        print(f"Bellhaven parent ID: {BELLHAVEN_PARENT_ID}")

        website_results, recognized_ids = classify_website_locations(
            website_locations,
            crm_accounts
        )

        crm_only_results = find_crm_only_accounts(
            crm_accounts,
            recognized_ids
        )

        summary = {}

        for item in website_results:
            classification = item["classification"]
            summary[classification] = summary.get(classification, 0) + 1

        print("\nWEBSITE CLASSIFICATION SUMMARY")

        for classification, count in sorted(summary.items()):
            print(f"{classification}: {count}")

        print(f"\nCRM-only accounts: {len(crm_only_results)}")

        output = {
            "parent_account_id": BELLHAVEN_PARENT_ID,
            "website_location_count": len(website_locations),
            "crm_account_count": len(crm_accounts),
            "website_classification_summary": summary,
            "website_results": website_results,
            "crm_only_accounts": crm_only_results,
        }

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

        with OUTPUT_FILE.open("w", encoding="utf-8") as file:
            json.dump(output, file, indent=4, default=str)

        print(f"\nResults saved to: {OUTPUT_FILE}")

    finally:
        session.close()


if __name__ == "__main__":
    main()
