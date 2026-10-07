"""relatório operacional: detalhe por fonte em collection_runs (coluna by_source, nula nas execuções antigas)

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collection_runs") as b:
        b.add_column(sa.Column("by_source", sa.JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("collection_runs") as b:
        b.drop_column("by_source")
