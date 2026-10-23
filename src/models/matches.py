import uuid

from sqlalchemy import (
    UUID,
    BigInteger,
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
)

from src.models.base import Base


class Matches(Base):
    """Матч турнира: соперники, победитель и счёт."""

    __tablename__ = "matches"

    id = Column(UUID, primary_key=True, index=True, default=uuid.uuid4)
    tour_id = Column(BigInteger, ForeignKey("tours.id"), index=True, nullable=False)
    first_player_id = Column(BigInteger, ForeignKey("players.id"), index=True, nullable=False)
    second_player_id = Column(BigInteger, ForeignKey("players.id"), index=True, nullable=False)
    # победителя может не быть: матч ещё не доигран или result неизвестен
    winner_player_id = Column(BigInteger, ForeignKey("players.id"), index=True, nullable=True)
    first_score = Column(Integer, nullable=True)
    second_score = Column(Integer, nullable=True)
    # счёт целиком, как его отдаёт API, например «6-4 3-6 7-5»
    score = Column(String, nullable=True)
    # состояние матча, как его отдаёт API
    status = Column(String, nullable=True)
    date = Column(Date, nullable=True)
    # этап турнира, в котором сыгран матч, — «Основной турнир»
    stage_name = Column(String, nullable=True)
    # круг, на котором сыгран матч, и сколько их всего в сетке
    round_on = Column(Integer, nullable=True)
    rounds = Column(Integer, nullable=True)
