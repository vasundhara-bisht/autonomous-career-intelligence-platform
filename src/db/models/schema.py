"""
MVP table definitions aligned with SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md.

Phase A: schema only — not used by pipeline persistence yet.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column("job_key", String(512), nullable=False)
    job_key_v2: Mapped[str] = mapped_column(
        "job_key_v2", String(255), nullable=False, unique=True, index=True
    )
    identity_source: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    company: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    location: Mapped[str | None] = mapped_column(String(512))
    source: Mapped[str | None] = mapped_column(String(64), index=True)
    link: Mapped[str | None] = mapped_column(Text)
    hiring_manager: Mapped[str | None] = mapped_column(String(512))
    time_posted: Mapped[str | None] = mapped_column(String(128))
    posted_at_date: Mapped[str | None] = mapped_column(String(32))
    age_days: Mapped[int | None] = mapped_column(Integer)
    listing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open", index=True
    )
    listing_status_reason: Mapped[str | None] = mapped_column(Text)
    listing_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    listing_check_attempted_at: Mapped[datetime | None] = mapped_column(DateTime)
    consecutive_check_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    listing_check_paused_at: Mapped[datetime | None] = mapped_column(DateTime)
    listing_closed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    listing_removed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    observations: Mapped[list["JobObservation"]] = relationship(back_populates="job")
    descriptions: Mapped[list["JobDescription"]] = relationship(back_populates="job")
    evaluations: Mapped[list["AiEvaluation"]] = relationship(back_populates="job")
    user_state: Mapped["UserJobState | None"] = relationship(
        back_populates="job", uselist=False
    )
    recruiter_links: Mapped[list["RecruiterJobLink"]] = relationship(
        back_populates="job"
    )


class AcquisitionRun(Base):
    __tablename__ = "acquisition_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    notes: Mapped[str | None] = mapped_column(Text)
    run_trigger: Mapped[str | None] = mapped_column(String(16))

    observations: Mapped[list["JobObservation"]] = relationship(back_populates="run")
    query_runs: Mapped[list["AcquisitionQueryRun"]] = relationship(
        back_populates="run"
    )
    evaluations: Mapped[list["AiEvaluation"]] = relationship(back_populates="run")


class AcquisitionQueryRun(Base):
    __tablename__ = "acquisition_query_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("acquisition_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    query_label: Mapped[str | None] = mapped_column(String(255))
    query_role: Mapped[str | None] = mapped_column(String(64))
    query_group: Mapped[str | None] = mapped_column(String(128))
    filter_profile: Mapped[str | None] = mapped_column(String(128))
    run_ts: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    jobs_collected: Mapped[int | None] = mapped_column(Integer)

    run: Mapped["AcquisitionRun"] = relationship(back_populates="query_runs")
    observations: Mapped[list["JobObservation"]] = relationship(
        back_populates="query_run"
    )


class JobObservation(Base):
    __tablename__ = "job_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("acquisition_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("acquisition_query_runs.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    times_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    job: Mapped["Job"] = relationship(back_populates="observations")
    run: Mapped["AcquisitionRun"] = relationship(back_populates="observations")
    query_run: Mapped["AcquisitionQueryRun | None"] = relationship(
        back_populates="observations"
    )


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_key_v2: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str | None] = mapped_column(String(64))
    last_updated: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="descriptions")


class AiEvaluation(Base):
    __tablename__ = "ai_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("acquisition_runs.id", ondelete="SET NULL"), index=True
    )
    ai_refresh_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_refresh_runs.id", ondelete="SET NULL"), index=True
    )
    ai_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ai_score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    job: Mapped["Job"] = relationship(back_populates="evaluations")
    run: Mapped["AcquisitionRun | None"] = relationship(back_populates="evaluations")
    ai_refresh_run: Mapped["AiRefreshRun | None"] = relationship(
        back_populates="evaluations"
    )


class AiRefreshRun(Base):
    __tablename__ = "ai_refresh_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    preset: Mapped[str] = mapped_column(String(32), nullable=False, default="backlog")
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persist_skipped_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    skipped_no_description: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    skipped_by_cap_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    batch_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    profile_path: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(Text)

    evaluations: Mapped[list["AiEvaluation"]] = relationship(
        back_populates="ai_refresh_run"
    )


class UserJobState(Base):
    __tablename__ = "user_job_state"

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rejected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    offer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pipeline_stage: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    job: Mapped["Job"] = relationship(back_populates="user_state")


class Recruiter(Base):
    __tablename__ = "recruiters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recruiter_key: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    recruiter_name: Mapped[str] = mapped_column(String(255), nullable=False)
    current_company: Mapped[str | None] = mapped_column(String(512))
    source: Mapped[str | None] = mapped_column(String(64))
    recruiter_title: Mapped[str | None] = mapped_column(String(255))
    recruiter_company: Mapped[str | None] = mapped_column(String(512))
    first_seen: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    jobs_connected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recruiter_stage: Mapped[str | None] = mapped_column(String(64))
    outreach_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recruiter_replied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    last_outreach_date: Mapped[str | None] = mapped_column(String(32))
    last_response_date: Mapped[str | None] = mapped_column(String(32))
    touchpoint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_interaction_note: Mapped[str | None] = mapped_column(Text)
    currently_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    job_links: Mapped[list["RecruiterJobLink"]] = relationship(back_populates="recruiter")


class RecruiterJobLink(Base):
    __tablename__ = "recruiter_job_links"
    __table_args__ = (
        UniqueConstraint("recruiter_id", "job_id", name="uq_recruiter_job"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recruiter_id: Mapped[int] = mapped_column(
        ForeignKey("recruiters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    recruiter: Mapped["Recruiter"] = relationship(back_populates="job_links")
    job: Mapped["Job"] = relationship(back_populates="recruiter_links")


class QueryCooldownState(Base):
    __tablename__ = "query_cooldown_state"

    query_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_run_at: Mapped[float | None] = mapped_column(Float)
    domain_rotation_index: Mapped[int | None] = mapped_column(Integer)


class LifecycleMonitorRun(Base):
    __tablename__ = "lifecycle_monitor_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    check_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paused_skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    terminal_skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    error_summary: Mapped[str | None] = mapped_column(Text)
    check_failed_rate: Mapped[float | None] = mapped_column(Float)
    monitor_health: Mapped[str | None] = mapped_column(String(16))
    systemic_alert: Mapped[str | None] = mapped_column(String(64))
    auth_health: Mapped[str | None] = mapped_column(String(16))
    parity_warning_summary: Mapped[str | None] = mapped_column(Text)
    provider_summary: Mapped[str | None] = mapped_column(Text)
    run_trigger: Mapped[str | None] = mapped_column(String(16))


class MonitorProviderState(Base):
    __tablename__ = "monitor_provider_state"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    health: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    reason: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime)
    backoff_until: Mapped[datetime | None] = mapped_column(DateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class OutreachAttempt(Base):
    __tablename__ = "outreach_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(512), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(255))
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    outreach_channel: Mapped[str] = mapped_column(String(64), nullable=False)
    outreach_message: Mapped[str | None] = mapped_column(Text)
    ai_recommended_message: Mapped[str | None] = mapped_column(Text)
    date_contacted: Mapped[str] = mapped_column(String(32), nullable=False)
    follow_up_date: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    opportunity_id: Mapped[str | None] = mapped_column(String(255))
    opportunity_url: Mapped[str | None] = mapped_column(Text)
    hiring_signal_type: Mapped[str | None] = mapped_column(String(64))
    hiring_signal_url: Mapped[str | None] = mapped_column(Text)
    outreach_type: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
