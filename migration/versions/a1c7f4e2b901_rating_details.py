"""rating details

Revision ID: a1c7f4e2b901
Revises: d503d7e1346b
Create Date: 2026-10-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c7f4e2b901'
down_revision: Union[str, Sequence[str], None] = 'd503d7e1346b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('rating_details',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tour_id', sa.BigInteger(), nullable=False),
    sa.Column('player_id', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.String(), nullable=True),
    sa.Column('points', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['tour_id'], ['tours.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tour_id', 'player_id', name='uq_rating_details_tour_player')
    )
    op.create_index(op.f('ix_rating_details_id'), 'rating_details', ['id'], unique=False)
    op.create_index(op.f('ix_rating_details_player_id'), 'rating_details', ['player_id'], unique=False)
    op.create_index(op.f('ix_rating_details_tour_id'), 'rating_details', ['tour_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_rating_details_tour_id'), table_name='rating_details')
    op.drop_index(op.f('ix_rating_details_player_id'), table_name='rating_details')
    op.drop_index(op.f('ix_rating_details_id'), table_name='rating_details')
    op.drop_table('rating_details')
