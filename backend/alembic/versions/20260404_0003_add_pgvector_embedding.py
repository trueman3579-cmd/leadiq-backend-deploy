"""Add pgvector extension and embedding column for semantic search

Revision ID: 20260404_0003
Revises: 20260327_0002
Create Date: 2026-04-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260404_0003"
down_revision = "20260327_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add embedding column to leads table (pgvector type)
    from pgvector.sqlalchemy import Vector
    op.add_column(
        "leads",
        sa.Column("embedding", Vector(768), nullable=True),
    )

    # Add indexes for the embedding column (raw SQL for pgvector dialect support)
    op.execute("CREATE INDEX IF NOT EXISTS ix_leads_embedding ON leads USING ivfflat (embedding vector_cosine_ops)")

    # Add missing columns from model
    op.add_column("leads", sa.Column("source", sa.String(length=64), nullable=True))
    op.add_column("leads", sa.Column("company_domain", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("source_actor", sa.String(length=100), nullable=True))
    op.add_column("leads", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("leads", sa.Column("tech_stack", sa.ARRAY(sa.String), nullable=True))
    op.add_column("leads", sa.Column("funding_stage", sa.String(length=50), nullable=True))
    op.add_column("leads", sa.Column("funding_amount", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("founded_year", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("intent_signals", sa.JSON, nullable=True, default=list))
    op.add_column("leads", sa.Column("icp_score", sa.Float(), nullable=True))

    # Add indexes for new columns
    op.create_index("ix_leads_company_domain", "leads", ["company_domain"], unique=False)
    op.create_index("ix_leads_stage", "leads", ["stage"], unique=False)
    op.create_index("ix_leads_confidence", "leads", ["confidence"], unique=False)
    op.create_index("ix_leads_source", "leads", ["source"], unique=False)
    op.create_index("ix_leads_created_at", "leads", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_leads_created_at", table_name="leads")
    op.drop_index("ix_leads_source", table_name="leads")
    op.drop_index("ix_leads_confidence", table_name="leads")
    op.drop_index("ix_leads_stage", table_name="leads")
    op.drop_index("ix_leads_company_domain", table_name="leads")
    op.drop_index("ix_leads_embedding", table_name="leads")

    op.drop_column("leads", "embedding")
    op.drop_column("leads", "company_domain")
    op.drop_column("leads", "source_url")
    op.drop_column("leads", "source_actor")
    op.drop_column("leads", "phone")
    op.drop_column("leads", "tech_stack")
    op.drop_column("leads", "funding_stage")
    op.drop_column("leads", "funding_amount")
    op.drop_column("leads", "founded_year")
    op.drop_column("leads", "intent_signals")
    op.drop_column("leads", "icp_score")

    # Drop pgvector extension (only if no longer needed)
    op.execute("DROP EXTENSION IF EXISTS vector")
