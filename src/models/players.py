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
from sqlalchemy.orm import relationship

from src.models.base import Base
from src.models.tours import tours_players


class Players(Base):
    """Игроки"""

    __tablename__ = "players"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String, nullable=False)
    birth_date = Column(Date, nullable=False)
    city = Column(String, nullable=True)

    tours = relationship(
        "Tours",
        secondary=tours_players,
        back_populates="players",
        lazy="selectin",
    )


class Points(Base):
    __tablename__ = "points"

    id = Column(UUID, primary_key=True, index=True, default=uuid.uuid4)
    players_id = Column(BigInteger, ForeignKey("players.id"), index=True, nullable=False)
    date = Column(Date, nullable=False)
    points = Column(Integer, nullable=False)
