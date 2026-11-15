"""Persist MCP resources and resource templates.

Revision ID: 0006_mcp_resources
Revises: 0005_user_display_name
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_mcp_resources"
down_revision: Union[str, None] = "0005_user_display_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_resources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("server_id", sa.String(length=36), nullable=False),
        sa.Column("uri", sa.String(length=2048), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "uri", name="uq_mcp_resources_server_id_uri"),
    )
    op.create_index("ix_mcp_resources_workspace_id", "mcp_resources", ["workspace_id"])
    op.create_index("ix_mcp_resources_server_id", "mcp_resources", ["server_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_resources_server_id", table_name="mcp_resources")
    op.drop_index("ix_mcp_resources_workspace_id", table_name="mcp_resources")
    op.drop_table("mcp_resources")
