"""Alembic migration: add email-verification columns to users table.

``UserOut`` exposes ``is_email_verified`` / ``email_verified_at`` and the ``User``
ORM model declares the backing columns, so existing databases need them too
(otherwise every user-serializing endpoint raises on attribute access).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260829_add_email_verification"
down_revision = "add_updated_at_to_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("email_verification_token", sa.String(length=512), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_verification_token_expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_email_verification_token", "users", ["email_verification_token"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_email_verification_token", table_name="users")
    op.drop_column("users", "email_verification_token_expires_at")
    op.drop_column("users", "email_verification_token")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "is_email_verified")
