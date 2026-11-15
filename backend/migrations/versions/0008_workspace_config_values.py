"""Add workspace variables and encrypted secrets.

Revision ID: 0008_workspace_config_values
Revises: 0007_binary_resources
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_workspace_config_values"
down_revision: Union[str, None] = "0007_binary_resources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_config_values",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("encrypted_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(kind = 'variable' AND value IS NOT NULL AND encrypted_value IS NULL) OR "
            "(kind = 'secret' AND value IS NULL AND encrypted_value IS NOT NULL)",
            name="ck_workspace_config_values_storage",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            name="uq_workspace_config_values_workspace_id_name",
        ),
    )
    op.create_index(
        "ix_workspace_config_values_workspace_id",
        "workspace_config_values",
        ["workspace_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    value_count = connection.execute(
        sa.text("SELECT count(*) FROM workspace_config_values")
    ).scalar_one()
    if value_count:
        raise RuntimeError(
            "Delete all workspace variables and secrets through the application "
            "before downgrading this migration."
        )

    op.drop_index(
        "ix_workspace_config_values_workspace_id",
        table_name="workspace_config_values",
    )
    op.drop_table("workspace_config_values")
