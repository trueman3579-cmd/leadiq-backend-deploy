"""Add company_context, gov_schemes, funding_events, job_signals tables with pgvector

Revision ID: 20260511_0001
Revises: 20260404_120000
Create Date: 2026-05-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID, JSONB

# revision identifiers, used by Alembic.
revision = "20260511_0001"
down_revision = "20260404_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── company_context ──────────────────────────────────────────────────────
    op.create_table(
        "company_context",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_name", sa.String(256), nullable=False, index=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False, index=True),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, default=0),
        sa.Column("embedding", sa.Text(), nullable=True),  # vector(384) handled at app layer
        sa.Column("trust_score", sa.Float(), nullable=False, default=5.0),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("""
        ALTER TABLE company_context
        ADD COLUMN IF NOT EXISTS embedding_vector vector(384)
    """)
    op.execute("COMMIT")
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS company_context_embedding_hnsw_idx
        ON company_context USING hnsw (embedding_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("COMMIT")
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_company_context_company
        ON company_context (company_name, source_type)
    """)

    # ── gov_schemes ────────────────────────────────────────────────────────
    op.create_table(
        "gov_schemes",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(512), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("eligibility", sa.Text(), nullable=False),
        sa.Column("deadline", sa.String(128), nullable=True),
        sa.Column("funding_amount", sa.String(256), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("department", sa.String(128), nullable=False, index=True),
        sa.Column("trust_score", sa.Float(), nullable=False, default=10.0),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("""
        ALTER TABLE gov_schemes
        ADD COLUMN IF NOT EXISTS embedding_vector vector(384)
    """)
    op.execute("COMMIT")
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS gov_schemes_embedding_hnsw_idx
        ON gov_schemes USING hnsw (embedding_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # ── funding_events ─────────────────────────────────────────────────────
    op.create_table(
        "funding_events",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_name", sa.String(256), nullable=False, index=True),
        sa.Column("amount", sa.String(128), nullable=True),
        sa.Column("round_type", sa.String(64), nullable=True, index=True),
        sa.Column("date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, index=True),
        sa.Column("location", sa.String(128), nullable=True),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("trust_score", sa.Float(), nullable=False, default=5.0),
        sa.Column("is_verified", sa.Boolean(), nullable=False, default=False),
        sa.Column("raw_excerpt", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("COMMIT")
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_funding_events_company_date
        ON funding_events (company_name, date DESC)
    """)
    op.execute("COMMIT")
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_funding_events_verified
        ON funding_events (is_verified, trust_score)
        WHERE is_verified = true
    """)

    # ── job_signals ────────────────────────────────────────────────────────
    op.create_table(
        "job_signals",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_name", sa.String(256), nullable=False, index=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("location", sa.String(128), nullable=True),
        sa.Column("work_mode", sa.String(32), nullable=True),
        sa.Column("experience", sa.String(64), nullable=True),
        sa.Column("skills", ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("salary_range", sa.String(128), nullable=True),
        sa.Column("posted_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, index=True),
        sa.Column("hiring_velocity", sa.Integer(), nullable=False, default=0),
        sa.Column("trust_score", sa.Float(), nullable=False, default=5.0),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("COMMIT")
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_job_signals_velocity
        ON job_signals (hiring_velocity DESC)
        WHERE hiring_velocity >= 70
    """)
    op.execute("COMMIT")
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_job_signals_company
        ON job_signals (company_name, posted_date DESC)
    """)


def downgrade() -> None:
    op.drop_table("job_signals")
    op.drop_table("funding_events")
    op.drop_table("gov_schemes")
    op.drop_table("company_context")
