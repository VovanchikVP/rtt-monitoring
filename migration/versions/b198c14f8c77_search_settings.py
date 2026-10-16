"""search settings

Revision ID: b198c14f8c77
Revises: d503d7e1346b
Create Date: 2026-10-16 07:08:43.777996

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b198c14f8c77'
down_revision: Union[str, Sequence[str], None] = 'd503d7e1346b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('search_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('period_months', sa.Integer(), nullable=False),
    sa.Column('per_page', sa.Integer(), nullable=False),
    sa.Column('tour_ranks', postgresql.ARRAY(sa.Integer()), nullable=False),
    sa.Column('tour_gender', sa.Integer(), nullable=False),
    sa.Column('location_ids', postgresql.ARRAY(sa.Integer()), nullable=False),
    sa.Column('age_groups', postgresql.ARRAY(sa.Integer()), nullable=False),
    sa.CheckConstraint('id = 1', name='ck_search_settings_single_row'),
    sa.PrimaryKeyConstraint('id')
    )
    # единственная строка настроек с параметрами поиска по умолчанию
    op.execute(
        "INSERT INTO search_settings "
        "(id, period_months, per_page, tour_ranks, tour_gender, location_ids, age_groups) "
        "VALUES (1, 3, 10, '{226}', 2, '{1419}', '{131,132}')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('search_settings')
