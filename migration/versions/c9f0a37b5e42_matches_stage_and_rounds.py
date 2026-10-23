"""matches stage and rounds

Revision ID: c9f0a37b5e42
Revises: f4a81d3c9b56
Create Date: 2026-10-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9f0a37b5e42'
down_revision: Union[str, Sequence[str], None] = 'f4a81d3c9b56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('matches', sa.Column('stage_name', sa.String(), nullable=True))
    op.add_column('matches', sa.Column('round_on', sa.Integer(), nullable=True))
    op.add_column('matches', sa.Column('rounds', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('matches', 'rounds')
    op.drop_column('matches', 'round_on')
    op.drop_column('matches', 'stage_name')
