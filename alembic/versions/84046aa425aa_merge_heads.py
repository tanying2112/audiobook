"""merge heads

Revision ID: 84046aa425aa
Revises: 9771997b7bdc, e4d685074691
Create Date: 2026-08-22 12:39:23.198454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84046aa425aa'
down_revision: Union[str, None] = ('9771997b7bdc', 'e4d685074691')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
