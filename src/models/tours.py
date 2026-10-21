from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
    Table,
    false,
)
from sqlalchemy.orm import relationship

from src.models.base import Base

# связь многие-ко-многим: турнир <-> участники
tours_players = Table(
    "tours_players",
    Base.metadata,
    Column("tour_id", BigInteger, ForeignKey("tours.id"), primary_key=True),
    Column("player_id", BigInteger, ForeignKey("players.id"), primary_key=True),
)


class Tours(Base):
    """Основная информация о турнире (метод API `tour.card.main`)"""

    __tablename__ = "tours"

    id = Column(BigInteger, primary_key=True, index=True)  # tour_id
    name = Column(String, nullable=True)
    location = Column(String, nullable=True)
    location_full = Column(String, nullable=True)
    begin_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    tour_members = Column(Integer, nullable=True)
    is_finished = Column(Boolean, nullable=False, default=False, server_default=false())

    players = relationship(
        "Players",
        secondary=tours_players,
        back_populates="tours",
        lazy="selectin",
    )
