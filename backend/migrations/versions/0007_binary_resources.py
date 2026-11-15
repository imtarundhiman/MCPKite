"""Support binary MCP resources and standard annotations.

Revision ID: 0007_binary_resources
Revises: 0006_mcp_resources
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_binary_resources"
down_revision: Union[str, None] = "0006_mcp_resources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "mcp_resources",
        "content",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.add_column(
        "mcp_resources",
        sa.Column(
            "content_kind",
            sa.String(length=8),
            nullable=False,
            server_default="text",
        ),
    )
    op.add_column("mcp_resources", sa.Column("object_key", sa.String(length=512)))
    op.add_column("mcp_resources", sa.Column("file_name", sa.String(length=255)))
    op.add_column("mcp_resources", sa.Column("size_bytes", sa.Integer()))
    op.add_column("mcp_resources", sa.Column("sha256", sa.String(length=64)))
    op.add_column(
        "mcp_resources",
        sa.Column(
            "audience",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column("mcp_resources", sa.Column("priority", sa.Float()))
    op.create_check_constraint(
        "ck_mcp_resources_content_storage",
        "mcp_resources",
        "(content_kind = 'text' AND content IS NOT NULL AND object_key IS NULL "
        "AND file_name IS NULL AND size_bytes IS NULL AND sha256 IS NULL) OR "
        "(content_kind = 'binary' AND content IS NULL AND object_key IS NOT NULL "
        "AND file_name IS NOT NULL AND size_bytes IS NOT NULL AND sha256 IS NOT NULL)",
    )


def downgrade() -> None:
    connection = op.get_bind()
    binary_count = connection.execute(
        sa.text("SELECT count(*) FROM mcp_resources WHERE content_kind = 'binary'")
    ).scalar_one()
    if binary_count:
        raise RuntimeError(
            "Delete all binary MCP resources through the application before "
            "downgrading this migration."
        )

    op.drop_constraint(
        "ck_mcp_resources_content_storage",
        "mcp_resources",
        type_="check",
    )
    op.drop_column("mcp_resources", "priority")
    op.drop_column("mcp_resources", "audience")
    op.drop_column("mcp_resources", "sha256")
    op.drop_column("mcp_resources", "size_bytes")
    op.drop_column("mcp_resources", "file_name")
    op.drop_column("mcp_resources", "object_key")
    op.drop_column("mcp_resources", "content_kind")
    op.alter_column(
        "mcp_resources",
        "content",
        existing_type=sa.Text(),
        nullable=False,
    )
