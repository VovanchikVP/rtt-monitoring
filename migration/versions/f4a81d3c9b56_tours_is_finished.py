"""tours is_finished

Revision ID: f4a81d3c9b56
Revises: e7b24c6f8a13
Create Date: 2026-10-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a81d3c9b56'
down_revision: Union[str, Sequence[str], None] = 'e7b24c6f8a13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default нужен, чтобы уже существующие строки получили false
    op.add_column(
        'tours',
        sa.Column('is_finished', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tours', 'is_finished')
