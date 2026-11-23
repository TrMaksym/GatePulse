"""merge migration heads

Revision ID: 18bd83a21901
Revises: 32df2ec472a1, 8f9f8547fa52
Create Date: 2026-11-23 13:18:52.407597

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '18bd83a21901'
down_revision: Union[str, Sequence[str], None] = ('32df2ec472a1', '8f9f8547fa52')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
