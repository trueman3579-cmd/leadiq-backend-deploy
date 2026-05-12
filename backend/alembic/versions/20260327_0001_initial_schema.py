"""Initial schema: posts, leads, feedback, quota_usage

Revision ID: 20260327_0001
Revises:
Create Date: 2026-03-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260327_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "posts",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("author", sa.String(length=256), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_post_source_ext"),
    )
    op.create_index("ix_posts_source", "posts", ["source"], unique=False)
    op.create_index("ix_posts_content_hash", "posts", ["content_hash"], unique=False)

    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("is_opportunity", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("urgency", sa.String(length=16), nullable=True),
        sa.Column("opportunity_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("icp_fit_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("final_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score_band", sa.String(length=16), nullable=False, server_default="cold"),
        sa.Column("company_name", sa.String(length=256), nullable=True),
        sa.Column("company_size", sa.String(length=32), nullable=True),
        sa.Column("industry", sa.String(length=128), nullable=True),
        sa.Column("contact_name", sa.String(length=256), nullable=True),
        sa.Column("contact_title", sa.String(length=256), nullable=True),
        sa.Column("stage", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("outreach_draft", sa.Text(), nullable=True),
        sa.Column("outreach_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id", name="uq_lead_post_id"),
    )
    op.create_index("ix_leads_post_id", "leads", ["post_id"], unique=False)

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=True),
        sa.Column("reviewer", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_lead_id", "feedback", ["lead_id"], unique=False)

    op.create_table(
        "quota_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "model", name="uq_quota_date_model"),
    )
    op.create_index("ix_quota_usage_date", "quota_usage", ["date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_quota_usage_date", table_name="quota_usage")
    op.drop_table("quota_usage")

    op.drop_index("ix_feedback_lead_id", table_name="feedback")
    op.drop_table("feedback")

    op.drop_index("ix_leads_post_id", table_name="leads")
    op.drop_table("leads")

    op.drop_index("ix_posts_content_hash", table_name="posts")
    op.drop_index("ix_posts_source", table_name="posts")
    op.drop_table("posts")
