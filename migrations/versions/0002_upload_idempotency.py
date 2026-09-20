"""add upload idempotency keys

Revision ID: 0002_upload_idempotency
Revises: 0001_reliable_upload_jobs
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_upload_idempotency"
down_revision: str | None = "0001_reliable_upload_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column(
        "documents",
        sa.Column("idempotency_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_documents_tenant_owner_idempotency_key",
        "documents",
        ["tenant", "owner", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_documents_tenant_owner_idempotency_key", table_name="documents")
    op.drop_column("documents", "idempotency_fingerprint")
    op.drop_column("documents", "idempotency_key")
