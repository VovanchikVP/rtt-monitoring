"""matches

Revision ID: e7b24c6f8a13
Revises: a1c7f4e2b901
Create Date: 2026-10-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b24c6f8a13'
down_revision: Union[str, Sequence[str], None] = 'a1c7f4e2b901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('matches',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tour_id', sa.BigInteger(), nullable=False),
    sa.Column('first_player_id', sa.BigInteger(), nullable=False),
    sa.Column('second_player_id', sa.BigInteger(), nullable=False),
    sa.Column('winner_player_id', sa.BigInteger(), nullable=True),
    sa.Column('first_score', sa.Integer(), nullable=True),
    sa.Column('second_score', sa.Integer(), nullable=True),
    sa.Column('score', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('date', sa.Date(), nullable=True),
    sa.ForeignKeyConstraint(['first_player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['second_player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['winner_player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['tour_id'], ['tours.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_matches_id'), 'matches', ['id'], unique=False)
    op.create_index(op.f('ix_matches_tour_id'), 'matches', ['tour_id'], unique=False)
    op.create_index(op.f('ix_matches_first_player_id'), 'matches', ['first_player_id'], unique=False)
    op.create_index(op.f('ix_matches_second_player_id'), 'matches', ['second_player_id'], unique=False)
    op.create_index(op.f('ix_matches_winner_player_id'), 'matches', ['winner_player_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_matches_winner_player_id'), table_name='matches')
    op.drop_index(op.f('ix_matches_second_player_id'), table_name='matches')
    op.drop_index(op.f('ix_matches_first_player_id'), table_name='matches')
    op.drop_index(op.f('ix_matches_tour_id'), table_name='matches')
    op.drop_index(op.f('ix_matches_id'), table_name='matches')
    op.drop_table('matches')
