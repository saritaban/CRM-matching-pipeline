
from src.database import SessionLocal
from src.models import WebsiteLocation, CRMAccount, Proposal

from src.matching import (
    calculate_match_score,
    classify_match
)


def generate_proposals():

    db = SessionLocal()

    try:
        website_records = db.query(WebsiteLocation).all()
        crm_records = db.query(CRMAccount).all()

        print(f"Website communities: {len(website_records)}")
        print(f"CRM accounts: {len(crm_records)}")

        created_count = 0
        updated_count = 0

        for website in website_records:

            candidates = []

            # Compare one website record with every CRM account
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
                    "field_scores": field_scores,
                    "has_address_evidence": has_address
                })

            # Sort candidates by highest score
            candidates.sort(
                key=lambda item: item["score"],
                reverse=True
            )

            top_candidates = candidates[:3]
            best_candidate = top_candidates[0] if top_candidates else None

            if best_candidate:

                classification = best_candidate["classification"]

                if classification == "High Confidence":
                    action_type = "LINK_EXISTING"
                    crm_account_id = best_candidate["account_id"]

                elif classification == "Possible Match":
                    action_type = "REVIEW_MATCH"
                    crm_account_id = best_candidate["account_id"]

                else:
                    action_type = "MANUAL_REVIEW"
                    crm_account_id = (
                        best_candidate["account_id"]
                        if best_candidate["has_address_evidence"]
                        else None
                    )

                confidence_score = best_candidate["score"]

            else:
                action_type = "MANUAL_REVIEW"
                crm_account_id = None
                confidence_score = 0
                classification = "No CRM Candidates"

            # Store matching evidence
            evidence = {
                "website_name": website.name,
                "website_address": {
                    "street": website.street,
                    "city": website.city,
                    "state": website.state,
                    "zip": website.zip
                },
                "classification": classification,
                "top_candidates": top_candidates
            }

            # Store the recommendation, not an actual CRM update
            recommended_changes = {
                "action": action_type,
                "website_location_id": website.id,
                "crm_account_id": crm_account_id,
                "description": (
                    "Link website community to existing CRM account"
                    if action_type == "LINK_EXISTING"
                    else "Review this candidate before taking action"
                )
            }

            # Check whether a pending proposal already exists
            existing_proposal = (
                db.query(Proposal)
                .filter(
                    Proposal.website_location_id == website.id,
                    Proposal.status == "Pending"
                )
                .first()
            )

            if existing_proposal:

                existing_proposal.crm_account_id = crm_account_id
                existing_proposal.action_type = action_type
                existing_proposal.confidence_score = confidence_score
                existing_proposal.evidence = evidence
                existing_proposal.recommended_changes = (
                    recommended_changes
                )

                updated_count += 1

            else:

                proposal = Proposal(
                    website_location_id=website.id,
                    crm_account_id=crm_account_id,
                    action_type=action_type,
                    confidence_score=confidence_score,
                    evidence=evidence,
                    recommended_changes=recommended_changes,
                    status="Pending"
                )

                db.add(proposal)
                created_count += 1

            print(
                f"{website.name} | "
                f"{classification} | "
                f"{confidence_score}% | "
                f"{action_type}"
            )

        # Save all proposals
        db.commit()

        print("\n========== PROPOSAL SUMMARY ==========")
        print(f"New proposals: {created_count}")
        print(f"Updated proposals: {updated_count}")
        print(
            f"Total processed communities: {len(website_records)}"
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    generate_proposals()
