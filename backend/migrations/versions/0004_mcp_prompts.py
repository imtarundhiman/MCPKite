"""Persist MCP prompt templates.

Revision ID: 0004_mcp_prompts
Revises: 0003_python_tool_drafts
Create Date: 2026-10-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_mcp_prompts"
down_revision: Union[str, None] = "0003_python_tool_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_prompts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("server_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "name", name="uq_mcp_prompts_server_id_name"),
    )
    op.create_index("ix_mcp_prompts_workspace_id", "mcp_prompts", ["workspace_id"])
    op.create_index("ix_mcp_prompts_server_id", "mcp_prompts", ["server_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_prompts_server_id", table_name="mcp_prompts")
    op.drop_index("ix_mcp_prompts_workspace_id", table_name="mcp_prompts")
    op.drop_table("mcp_prompts")
