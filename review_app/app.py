
import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

import streamlit as st

# --------------------------------------------------
# 1. PROJECT CONFIGURATION
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import SessionLocal
from src.models import (
    WebsiteLocation,
    CRMAccount,
    Proposal,
    ProposalAudit,
)

st.set_page_config(
    page_title="Bellhaven CRM Matching Review",
    page_icon="🏢",
    layout="wide",
)

st.title("Bellhaven CRM Matching Review")
st.caption("Review and approve proposed matches between website communities and CRM accounts.")

# --------------------------------------------------
# 2. HELPER FUNCTIONS
# --------------------------------------------------

def get_attr(obj, *names, default=None):
    """Return the first available attribute from an object."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def json_safe(value):
    """Convert Decimal and datetime values into JSON-compatible values."""
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]

    return value


def get_proposal_id(proposal):
    return get_attr(proposal, "id", "proposal_id")


def get_website_location(db, proposal):
    website_id = get_attr(
        proposal,
        "website_location_id",
        "website_id",
        "location_id",
    )

    if website_id is not None:
        return db.query(WebsiteLocation).filter(
            WebsiteLocation.id == website_id
        ).first()

    return None


def get_crm_account(db, proposal):
    account_id = proposal.crm_account_id

    if not account_id:
        return None

    return db.query(CRMAccount).filter(
        CRMAccount.account_id == account_id
    ).first()


# --------------------------------------------------
# 3. LOAD PROPOSALS
# --------------------------------------------------

def get_proposals():
    db = SessionLocal()

    try:
        proposals = (
            db.query(Proposal)
            .order_by(Proposal.confidence_score.desc())
            .all()
        )

        results = []

        for proposal in proposals:
            website = get_website_location(db, proposal)
            crm = get_crm_account(db, proposal)

            results.append({
                "proposal": proposal,
                "website": website,
                "crm": crm,
            })

        return results

    finally:
        db.close()


# --------------------------------------------------
# 4. SAVE REVIEW DECISION
# --------------------------------------------------

def save_review_decision(proposal_id, decision, reviewer):

    db = SessionLocal()

    try:
        # Lock the proposal row while processing the decision.
        proposal = (
            db.query(Proposal)
            .filter(Proposal.id == proposal_id)
            .with_for_update()
            .first()
        )

        if proposal is None:
            return False, "Proposal not found."

        # Prevent repeated approval or rejection.
        if proposal.status != "Pending":
            return False, f"This proposal has already been {proposal.status.lower()}."

        if decision == "Approved" and not proposal.crm_account_id:
            return False, "Cannot approve a proposal without a CRM account."

        if decision not in ("Approved", "Rejected"):
            return False, "Invalid review decision."

        reviewed_at = datetime.now(timezone.utc)

        proposal.status = decision

        if hasattr(proposal, "reviewed_by"):
            proposal.reviewed_by = reviewer

        if hasattr(proposal, "reviewed_at"):
            proposal.reviewed_at = reviewed_at

        # Prepare JSON-compatible audit details.
        details = {
            "crm_account_id": proposal.crm_account_id,
            "action_type": proposal.action_type,
            "confidence_score": (
                float(proposal.confidence_score)
                if proposal.confidence_score is not None
                else None
            ),
            "reviewed_at": reviewed_at.isoformat(),
        }

        audit = ProposalAudit(
            proposal_id=proposal_id,
            action=decision,
            performed_by=reviewer,
            details=json_safe(details),
        )

        db.add(audit)

        # Commit proposal status and audit record together.
        db.commit()

        return True, f"Proposal {decision.lower()} successfully."

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


# --------------------------------------------------
# 5. LOAD DASHBOARD DATA
# --------------------------------------------------

try:
    records = get_proposals()
except Exception as e:
    st.error(f"Unable to load proposals: {e}")
    st.stop()


# --------------------------------------------------
# 6. DISPLAY SUCCESS / ERROR FEEDBACK
# --------------------------------------------------

if "flash_message" in st.session_state:
    message_type, message = st.session_state.pop("flash_message")

    if message_type == "success":
        st.success(message)
    else:
        st.error(message)


# --------------------------------------------------
# 7. METRICS
# --------------------------------------------------

total = len(records)

pending = sum(
    1 for r in records if r["proposal"].status == "Pending"
)

approved = sum(
    1 for r in records if r["proposal"].status == "Approved"
)

rejected = sum(
    1 for r in records if r["proposal"].status == "Rejected"
)

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Proposals", total)
col2.metric("Pending", pending)
col3.metric("Approved", approved)
col4.metric("Rejected", rejected)

st.divider()


# --------------------------------------------------
# 8. FILTERS
# --------------------------------------------------

st.subheader("Proposal Overview")

filter_col1, filter_col2 = st.columns(2)

with filter_col1:
    status_filter = st.selectbox(
        "Filter by Status",
        ["All", "Pending", "Approved", "Rejected"],
    )

with filter_col2:
    action_filter = st.selectbox(
        "Filter by Recommendation",
        [
            "All",
            "LINK_EXISTING",
            "REVIEW_MATCH",
            "MANUAL_REVIEW",
        ],
    )


filtered_records = []

for record in records:

    proposal = record["proposal"]

    if status_filter != "All" and proposal.status != status_filter:
        continue

    if action_filter != "All" and proposal.action_type != action_filter:
        continue

    filtered_records.append(record)


# --------------------------------------------------
# 9. PROPOSAL TABLE
# --------------------------------------------------

table_data = []

for record in filtered_records:

    proposal = record["proposal"]
    website = record["website"]
    crm = record["crm"]

    table_data.append({
        "Proposal ID": get_proposal_id(proposal),
        "Website Community": (
            website.name if website else "Not available"
        ),
        "CRM Account": (
            crm.account_name if crm else "No CRM match"
        ),
        "Confidence": (
            float(proposal.confidence_score)
            if proposal.confidence_score is not None
            else None
        ),
        "Recommendation": proposal.action_type,
        "Status": proposal.status,
    })


if table_data:
    st.dataframe(
        table_data,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No proposals match the selected filters.")


st.divider()


# --------------------------------------------------
# 10. SELECT A PROPOSAL
# --------------------------------------------------

st.subheader("Review Individual Proposal")

pending_records = [
    r for r in filtered_records
    if r["proposal"].status == "Pending"
]

if not filtered_records:
    st.info("There are no proposals to display.")
    st.stop()


proposal_options = [
    get_proposal_id(r["proposal"])
    for r in filtered_records
]

selected_id = st.selectbox(
    "Select Proposal",
    proposal_options,
    format_func=lambda pid: next(
        (
            f"Proposal {pid} - "
            f"{r['website'].name if r['website'] else 'Unknown community'}"
            for r in filtered_records
            if get_proposal_id(r["proposal"]) == pid
        ),
        f"Proposal {pid}",
    ),
)

selected_record = next(
    r for r in filtered_records
    if get_proposal_id(r["proposal"]) == selected_id
)

proposal = selected_record["proposal"]
website = selected_record["website"]
crm = selected_record["crm"]


# --------------------------------------------------
# 11. WEBSITE AND CRM DETAILS
# --------------------------------------------------

st.markdown("### Community and CRM Comparison")

website_col, crm_col = st.columns(2)

with website_col:

    st.markdown("#### Website Information")

    if website:

        st.write("**Community Name:**", website.name)
        st.write("**Street:**", website.street)
        st.write("**City:**", website.city)
        st.write("**State:**", website.state)
        st.write("**ZIP:**", website.zip)
        st.write("**Care Offerings:**", website.care_offerings)
        st.write("**Source URL:**", website.source_url)

    else:
        st.warning("Website information not available.")


with crm_col:

    st.markdown("#### CRM Account Information")

    if crm:

        raw_data = crm.raw_data or {}

        st.write("**Account Name:**", get_attr(crm, "account_name", default="Not available"))
        st.write("**Account ID:**", get_attr(crm, "account_id", default="Not available"))

        st.write("**Street:**", get_attr(crm, "street", default="Not available"))
        st.write("**City:**", get_attr(crm, "city", default="Not available"))
        st.write("**State:**", get_attr(crm, "state", default="Not available"))
        st.write("**ZIP:**", get_attr(crm, "zip", default="Not available"))

        st.write(
            "**Care Type:**",
            get_attr(crm, "care_type", default=None)
            or raw_data.get("care_type", "Not available")
        )

        st.write(
            "**Status:**",
            get_attr(crm, "status", default=None)
            or raw_data.get("status", "Not available")
        )

    else:
        st.warning("No CRM account linked to this proposal.")

# --------------------------------------------------
# 12. MATCHING EVIDENCE
# --------------------------------------------------

st.divider()

st.markdown("### Matching Results")

confidence = (
    float(proposal.confidence_score)
    if proposal.confidence_score is not None
    else 0.0
)

col1, col2, col3 = st.columns(3)

col1.metric("Match Confidence", f"{confidence:.2f}%")
col2.metric("Recommendation", proposal.action_type)
col3.metric("Current Status", proposal.status)

st.markdown("#### Matching Evidence")

evidence = json_safe(proposal.evidence)

if evidence:
    st.json(evidence)
else:
    st.info("No matching evidence available.")


st.markdown("#### Recommended Changes")

recommended_changes = json_safe(proposal.recommended_changes)

if recommended_changes:
    st.json(recommended_changes)
else:
    st.info("No recommended changes available.")


# --------------------------------------------------
# 13. REVIEW ACTIONS
# --------------------------------------------------

st.divider()

st.markdown("### Reviewer Decision")

reviewer = st.text_input(
    "Reviewer Name",
    placeholder="Enter your name",
)

if proposal.status == "Pending":

    if not reviewer.strip():
        st.info("Enter your reviewer name before making a decision.")

    approve_col, reject_col = st.columns(2)

    with approve_col:

        if st.button(
            "Approve Match",
            key=f"approve_{selected_id}",
            type="primary",
            use_container_width=True,
            disabled=not reviewer.strip() or not proposal.crm_account_id,
        ):

            try:
                success, message = save_review_decision(
                    selected_id,
                    "Approved",
                    reviewer.strip(),
                )

                if success:
                    st.session_state["flash_message"] = (
                        "success",
                        message,
                    )
                    st.rerun()
                else:
                    st.warning(message)

            except Exception as e:
                st.error(f"Approval failed: {e}")

    with reject_col:

        if st.button(
            "Reject Match",
            key=f"reject_{selected_id}",
            use_container_width=True,
            disabled=not reviewer.strip(),
        ):

            try:
                success, message = save_review_decision(
                    selected_id,
                    "Rejected",
                    reviewer.strip(),
                )

                if success:
                    st.session_state["flash_message"] = (
                        "success",
                        message,
                    )
                    st.rerun()
                else:
                    st.warning(message)

            except Exception as e:
                st.error(f"Rejection failed: {e}")

else:

    st.success(
        f"This proposal has already been reviewed: {proposal.status}"
    )

    st.write(
        "**Reviewed by:**",
        get_attr(proposal, "reviewed_by", default="Not available"),
    )

    st.write(
        "**Reviewed at:**",
        get_attr(proposal, "reviewed_at", default="Not available"),
    )


# --------------------------------------------------
# 14. SAFETY NOTICE
# --------------------------------------------------

st.divider()

st.caption(
    "Safety notice: Approving or rejecting a proposal only records "
    "the review decision in PostgreSQL. No CRM account is created, "
    "modified, merged, or deleted by this dashboard."
)
