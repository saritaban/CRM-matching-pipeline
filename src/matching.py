
from rapidfuzz import fuzz

from src.database import SessionLocal
from src.models import WebsiteLocation, CRMAccount

from src.normalize import (
    normalize_company_name,
    normalize_street,
    normalize_city,
    normalize_state,
    normalize_zip
)


WEIGHTS = {
    "name": 40,
    "street": 30,
    "city": 10,
    "state": 10,
    "zip": 10
}


def similarity(value1, value2):

    if not value1 or not value2:
        return None

    return fuzz.token_set_ratio(value1, value2)


'''def calculate_match_score(website, crm):

    website_fields = {
        "name": normalize_company_name(website.name),
        "street": normalize_street(website.street),
        "city": normalize_city(website.city),
        "state": normalize_state(website.state),
        "zip": normalize_zip(website.zip)
    }

    crm_fields = {
        "name": normalize_company_name(crm.account_name),
        "street": normalize_street(crm.street),
        "city": normalize_city(crm.city),
        "state": normalize_state(crm.state),
        "zip": normalize_zip(crm.zip)
    }

    total_weight = 0
    weighted_score = 0
    field_scores = {}

    for field, weight in WEIGHTS.items():

        value1 = website_fields[field]
        value2 = crm_fields[field]

        score = similarity(value1, value2)

        if score is None:
            continue

        weighted_score += score * weight
        total_weight += weight

        field_scores[field] = round(score, 2)

    if total_weight == 0:
        return 0, field_scores, False

    final_score = weighted_score / total_weight

    # Require at least one address field comparison
    address_fields = ["street", "city", "state", "zip"]

    has_address_evidence = any(
        field in field_scores
        for field in address_fields
    )

    return round(final_score, 2), field_scores, has_address_evidence


def classify_match(score, has_address_evidence):

    if not has_address_evidence:
        return "Insufficient Address Evidence"

    if score >= 90:
        return "High Confidence"

    elif score >= 75:
        return "Possible Match"

    else:
        return "Low Confidence"
'''

def calculate_match_score(website, crm):

    website_fields = {
        "name": normalize_company_name(website.name),
        "street": normalize_street(website.street),
        "city": normalize_city(website.city),
        "state": normalize_state(website.state),
        "zip": normalize_zip(website.zip)
    }

    crm_fields = {
        "name": normalize_company_name(crm.account_name),
        "street": normalize_street(crm.street),
        "city": normalize_city(crm.city),
        "state": normalize_state(crm.state),
        "zip": normalize_zip(crm.zip)
    }

    field_scores = {}
    total_weight = 0
    weighted_score = 0

    # Company name: fuzzy comparison
    if website_fields["name"] and crm_fields["name"]:
        score = fuzz.token_set_ratio(
            website_fields["name"],
            crm_fields["name"]
        )
        field_scores["name"] = round(score, 2)
        weighted_score += score * WEIGHTS["name"]
        total_weight += WEIGHTS["name"]

    # Street: fuzzy comparison
    if website_fields["street"] and crm_fields["street"]:
        score = fuzz.token_set_ratio(
            website_fields["street"],
            crm_fields["street"]
        )
        field_scores["street"] = round(score, 2)
        weighted_score += score * WEIGHTS["street"]
        total_weight += WEIGHTS["street"]

    # City, state and ZIP: exact comparison
    for field in ["city", "state", "zip"]:

        value1 = website_fields[field]
        value2 = crm_fields[field]

        if value1 and value2:

            score = 100 if value1 == value2 else 0

            field_scores[field] = score
            weighted_score += score * WEIGHTS[field]
            total_weight += WEIGHTS[field]

    if total_weight == 0:
        return 0, field_scores, False

    final_score = weighted_score / total_weight

    # Count supporting address fields
    address_matches = sum(
        1 for field in ["city", "state", "zip"]
        if field in field_scores and field_scores[field] == 100
    )

    if (
        "street" in field_scores
        and field_scores["street"] >= 90
    ):
        address_matches += 1

    has_address_evidence = address_matches >= 2

    return (
        round(final_score, 2),
        field_scores,
        has_address_evidence
    )


def classify_match(score, has_address_evidence):

    if not has_address_evidence:
        return "Insufficient Address Evidence"

    if score >= 90:
        return "High Confidence"

    elif score >= 75:
        return "Possible Match"

    else:
        return "Low Confidence"


def run_matching():

    db = SessionLocal()

    try:

        website_records = db.query(WebsiteLocation).all()
        crm_records = db.query(CRMAccount).all()

        print(f"Website records: {len(website_records)}")
        print(f"CRM records: {len(crm_records)}")

        print("\n========== MATCHING RESULTS ==========\n")

        for website in website_records:

            candidates = []

            for crm in crm_records:

                score, field_scores, has_address = (
                    calculate_match_score(website, crm)
                )

                classification = classify_match(
                    score,
                    has_address
                )

                candidates.append({
                    "account_id": crm.account_id,
                    "account_name": crm.account_name,
                    "score": score,
                    "classification": classification,
                    "field_scores": field_scores
                })

            candidates.sort(
                key=lambda x: x["score"],
                reverse=True
            )

            print(f"\nWebsite: {website.name}")
            print("-" * 60)

            for candidate in candidates[:3]:

                print(
                    f"CRM: {candidate['account_name']} | "
                    f"ID: {candidate['account_id']} | "
                    f"Score: {candidate['score']}% | "
                    f"Result: {candidate['classification']}"
                )

                print(
                    f"Field scores: {candidate['field_scores']}"
                )

    finally:
        db.close()


if __name__ == "__main__":
    run_matching()
