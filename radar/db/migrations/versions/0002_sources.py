"""fontes: tabela sources e colunas de origem/corpo em news

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

from radar.db.tables import UTCDateTime

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("news") as b:
        b.add_column(sa.Column("source_id", sa.String(80)))
        b.add_column(sa.Column("source_type", sa.String(30)))
        b.add_column(sa.Column("body_status", sa.String(12), nullable=False, server_default="none"))
        b.add_column(sa.Column("tags", sa.JSON, nullable=False, server_default="[]"))
        b.add_column(sa.Column("canonical_url", sa.Text))
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.String(80), nullable=False, unique=True),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("tier", sa.Integer, nullable=False),
        sa.Column("etag", sa.String(255)),
        sa.Column("last_modified", sa.String(80)),
        sa.Column("last_fetch_at", UTCDateTime),
        sa.Column("last_success_at", UTCDateTime),
        sa.Column("last_status", sa.String(40)),
        sa.Column("last_error", sa.Text),
        sa.Column("consecutive_failures", sa.Integer, nullable=False),
        sa.Column("fetches_ok", sa.Integer, nullable=False),
        sa.Column("fetches_failed", sa.Integer, nullable=False),
        sa.Column("items_seen", sa.Integer, nullable=False),
        sa.Column("items_matched", sa.Integer, nullable=False),
        sa.Column("items_stored", sa.Integer, nullable=False),
        sa.Column("created_at", UTCDateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sources")
    with op.batch_alter_table("news") as b:
        for c in ("canonical_url", "tags", "body_status", "source_type", "source_id"):
            b.drop_column(c)
