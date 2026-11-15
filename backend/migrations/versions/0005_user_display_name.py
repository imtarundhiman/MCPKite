"""Add display names to user accounts.

Revision ID: 0005_user_display_name
Revises: 0004_mcp_prompts
Create Date: 2026-11-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_user_display_name"
down_revision: Union[str, None] = "0004_mcp_prompts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("display_name", sa.String(length=100), nullable=True),
    )

    users = sa.table(
        "users",
        sa.column("id", sa.String(length=36)),
        sa.column("email", sa.String(length=320)),
        sa.column("display_name", sa.String(length=100)),
    )
    connection = op.get_bind()
    existing_users = connection.execute(sa.select(users.c.id, users.c.email))
    for user_id, email in existing_users:
        display_name = email.split("@", 1)[0].strip()
        if not display_name:
            display_name = email
        connection.execute(
            users.update()
            .where(users.c.id == user_id)
            .values(display_name=display_name)
        )

    op.alter_column(
        "users",
        "display_name",
        existing_type=sa.String(length=100),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("users", "display_name")
