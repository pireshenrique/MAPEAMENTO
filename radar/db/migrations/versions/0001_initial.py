"""schema inicial

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

from radar.db.tables import UTCDateTime

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "competitors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("aliases", sa.JSON, nullable=False),
        sa.Column("domains", sa.JSON, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("created_at", UTCDateTime, nullable=False),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False),
    )
    op.create_table(
        "news",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_collector", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(255)),
        sa.Column("competitor_id", sa.Integer, sa.ForeignKey("competitors.id"), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("url_normalized", sa.String(1000), nullable=False),
        sa.Column("title_normalized", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(255)),
        sa.Column("source_domain", sa.String(255)),
        sa.Column("author", sa.String(255)),
        sa.Column("published_at", UTCDateTime, nullable=False),
        sa.Column("image_url", sa.Text),
        sa.Column("raw_content", sa.Text),
        sa.Column("match_confidence", sa.Float, nullable=False),
        sa.Column("match_evidence", sa.JSON, nullable=False),
        sa.Column("dup_status", sa.String(20), nullable=False),
        sa.Column("dup_of_id", sa.Integer, sa.ForeignKey("news.id")),
        sa.Column("dup_score", sa.Float),
        sa.Column("analysis_status", sa.String(10), nullable=False),
        sa.Column("analysis_attempts", sa.Integer, nullable=False),
        sa.Column("collected_at", UTCDateTime, nullable=False),
        sa.Column("created_at", UTCDateTime, nullable=False),
        sa.UniqueConstraint("competitor_id", "url_normalized", name="uq_news_competitor_url"),
    )
    op.create_index("ix_news_external", "news", ["source_collector", "external_id"])
    op.create_index("ix_news_published_at", "news", ["published_at"])
    op.create_index("ix_news_title_norm", "news", ["title_normalized"])
    op.create_index("ix_news_analysis_status", "news", ["analysis_status"])
    op.create_table(
        "news_analysis",
        sa.Column("news_id", sa.Integer, sa.ForeignKey("news.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("is_relevant", sa.Boolean, nullable=False),
        sa.Column("relevance_score", sa.Integer, nullable=False),
        sa.Column("competitive_impact", sa.String(10), nullable=False),
        sa.Column("sentiment", sa.String(10), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("subcategory", sa.String(120)),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("key_points", sa.JSON, nullable=False),
        sa.Column("strategic_reason", sa.Text, nullable=False),
        sa.Column("analyzed_at", UTCDateTime, nullable=False),
        sa.Column("model_used", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("raw_response", sa.Text),
    )
    op.create_index("ix_analysis_relevance", "news_analysis", ["relevance_score"])
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("started_at", UTCDateTime, nullable=False),
        sa.Column("finished_at", UTCDateTime),
        sa.Column("found", sa.Integer, nullable=False),
        sa.Column("new", sa.Integer, nullable=False),
        sa.Column("duplicates", sa.Integer, nullable=False),
        sa.Column("discarded", sa.Integer, nullable=False),
        sa.Column("analyzed", sa.Integer, nullable=False),
        sa.Column("failed", sa.Integer, nullable=False),
        sa.Column("errors", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    for t in ("collection_runs", "news_analysis", "news", "categories", "competitors"):
        op.drop_table(t)
