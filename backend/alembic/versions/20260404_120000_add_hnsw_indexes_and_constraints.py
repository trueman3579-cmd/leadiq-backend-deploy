"""Add HNSW vector index, composite indexes, CHECK constraints

Revision ID: 20260404_120000
Revises: 20260404_0003
Create Date: 2026-04-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY


# revision identifiers, used by Alembic.
revision = "20260404_120000"
down_revision = "20260404_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Install pgvector if not installed
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add embedding column if missing (in case migration 0003 failed)
    op.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='leads' AND column_name='embedding'
            ) THEN
                ALTER TABLE leads ADD COLUMN embedding vector(768);
            END IF;
        END $$
    ''')

    # HNSW index — better than IVFFlat for most use cases
    op.execute("COMMIT")
    op.execute('''
        CREATE INDEX CONCURRENTLY IF NOT EXISTS leads_embedding_hnsw_idx
        ON leads USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    ''')

    # Composite indexes for dashboard query patterns
    op.execute("COMMIT")
    op.execute('''
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lead_stage_created
        ON leads (stage, created_at)
    ''')
    op.execute("COMMIT")
    op.execute('''
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lead_icp_stage
        ON leads (icp_fit_score, stage)
        WHERE icp_fit_score IS NOT NULL
    ''')
    op.execute("COMMIT")
    op.execute('''
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lead_post_created
        ON leads (post_id, created_at)
    ''')
    op.execute("COMMIT")
    op.execute('''
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lead_final_score
        ON leads (final_score)
        WHERE final_score IS NOT NULL
    ''')

    # CHECK constraints
    op.add_column("leads", sa.Column("pain_point", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("raw_excerpt", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("india_signals", sa.ARRAY(sa.String()), nullable=True, server_default="{}"))
    op.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_lead_icp_score_range'
            ) THEN
                ALTER TABLE leads
                ADD CONSTRAINT ck_lead_icp_score_range
                CHECK (icp_fit_score IS NULL OR
                       (icp_fit_score >= 0.0 AND icp_fit_score <= 100.0));
            END IF;
        END $$
    ''')


def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS leads_embedding_hnsw_idx")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_lead_stage_created")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_lead_icp_stage")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_lead_post_created")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_lead_final_score")
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS ck_lead_confidence_range")
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS ck_lead_icp_score_range")
