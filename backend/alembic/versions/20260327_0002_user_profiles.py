"""20260327_0002_user_profiles — Add user_profiles table for adaptive personalization.

Revision ID: 0002
Revises: 20260327_0001_initial_schema
Create Date: 2026-03-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision     = "20260327_0002"
down_revision = "20260327_0001"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id",                    sa.Integer(),         primary_key=True, autoincrement=True),
        sa.Column("mode",                  sa.String(32),        nullable=False, server_default="b2b_sales"),
        sa.Column("product_description",   sa.Text(),            nullable=True),
        sa.Column("target_customer",       sa.Text(),            nullable=True),
        sa.Column("target_industries",     JSONB(),              nullable=False, server_default="[]"),
        sa.Column("target_company_sizes",  JSONB(),              nullable=False, server_default="[]"),
        sa.Column("include_keywords",      JSONB(),              nullable=False, server_default="[]"),
        sa.Column("exclude_keywords",      JSONB(),              nullable=False, server_default="[]"),
        sa.Column("hiring_roles",          JSONB(),              nullable=False, server_default="[]"),
        sa.Column("skills",                JSONB(),              nullable=False, server_default="[]"),
        sa.Column("min_salary",            sa.Integer(),         nullable=False, server_default="0"),
        sa.Column("remote_only",           sa.Boolean(),         nullable=False, server_default="false"),
        sa.Column("feedback_adjustments",  JSONB(),              nullable=False, server_default="{}"),
        sa.Column("created_at",            sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at",            sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
