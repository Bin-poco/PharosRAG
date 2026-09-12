"""create durable document ingestion tables

Revision ID: 0001_reliable_upload_jobs
Revises:
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_reliable_upload_jobs"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("document_id", sa.String(length=80), nullable=False),
        sa.Column("tenant", sa.String(length=160), nullable=False),
        sa.Column("owner", sa.String(length=160), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("source_format", sa.String(length=32), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("access_scope", sa.String(length=32), nullable=False),
        sa.Column("groups", sa.JSON(), nullable=False),
        sa.Column("acl", sa.JSON(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("parser_batch_id", sa.String(length=160), nullable=True),
        sa.Column("current_job_id", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("document_id"),
        sa.UniqueConstraint("current_job_id"),
    )
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_tenant", "documents", ["tenant"])
    op.create_index("ix_documents_tenant_owner", "documents", ["tenant", "owner"])
    op.create_index("ix_documents_tenant_sha256", "documents", ["tenant", "sha256"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("job_id", sa.String(length=80), nullable=False),
        sa.Column("document_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("celery_task_id", sa.String(length=80), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.document_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_ingestion_jobs_document_id", "ingestion_jobs", ["document_id"])
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index("ix_ingestion_jobs_status_available", "ingestion_jobs", ["status", "available_at"])

    op.create_table(
        "job_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_job_outbox_status", "job_outbox", ["status"])
    op.create_index("ix_job_outbox_status_next", "job_outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_table("job_outbox")
    op.drop_table("ingestion_jobs")
    op.drop_table("documents")
