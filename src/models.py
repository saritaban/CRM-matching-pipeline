from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Numeric,
    Boolean,
    DateTime,
    ForeignKey,
    func
)

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .database import Base


class WebsiteLocation(Base):
    __tablename__ = "website_locations"

    id = Column(Integer, primary_key=True)

    name = Column(String(255), nullable=False)
    street = Column(String(255))
    city = Column(String(100))
    state = Column(String(50))
    zip = Column(String(20))

    care_offerings = Column(JSONB, default=list)

    source_url = Column(String(500), unique=True, nullable=False)

    raw_data = Column(JSONB)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )


class CRMAccount(Base):
    __tablename__ = "crm_accounts"

    account_id = Column(String(100), primary_key=True)

    account_name = Column(String(255), nullable=False)

    parent_account_id = Column(String(100))

    street = Column(String(255))
    city = Column(String(100))
    state = Column(String(50))
    zip = Column(String(20))

    lifetime_revenue = Column(Numeric(15, 2))
    outstanding_ar = Column(Numeric(15, 2))

    chow_current_account = Column(String(100))
    duplicate_of_account = Column(String(100))

    status = Column(String(50))

    raw_data = Column(JSONB)

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)

    started_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    completed_at = Column(DateTime(timezone=True))

    status = Column(String(50))

    website_records = Column(Integer, default=0)
    crm_records = Column(Integer, default=0)
    proposals_created = Column(Integer, default=0)

    error_message = Column(Text)


class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True)

    website_location_id = Column(
        Integer,
        ForeignKey("website_locations.id")
    )

    crm_account_id = Column(String(100))

    action_type = Column(String(100), nullable=False)

    confidence_score = Column(Numeric(5, 2))

    evidence = Column(JSONB)

    recommended_changes = Column(JSONB)

    status = Column(
        String(50),
        default="Pending",
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    reviewed_at = Column(DateTime(timezone=True))

    reviewed_by = Column(String(255))

    execution_result = Column(JSONB)


class ProposalAudit(Base):
    __tablename__ = "proposal_audit"

    id = Column(Integer, primary_key=True)

    proposal_id = Column(
        Integer,
        ForeignKey("proposals.id"),
        nullable=False
    )

    action = Column(String(100), nullable=False)

    performed_by = Column(String(255))

    details = Column(JSONB)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )