import uuid

from sqlalchemy import (
    UUID,
    BigInteger,
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from src.models.base import Base


class RatingDetails(Base):
    """Результат игрока в турнире: место и начисленные очки."""

    __tablename__ = "rating_details"
    # за один турнир по игроку не больше одной записи
    __table_args__ = (
        UniqueConstraint("tour_id", "player_id", name="uq_rating_details_tour_player"),
    )

    id = Column(UUID, primary_key=True, index=True, default=uuid.uuid4)
    tour_id = Column(BigInteger, ForeignKey("tours.id"), index=True, nullable=False)
    player_id = Column(BigInteger, ForeignKey("players.id"), index=True, nullable=False)
    position = Column(String, nullable=True)  # может быть диапазоном, например «17-32»
    points = Column(Integer, nullable=True)
