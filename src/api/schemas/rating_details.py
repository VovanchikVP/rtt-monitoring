from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RatingDetailsRead(BaseModel):
    """Результат игрока в турнире: место и начисленные очки."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tour_id: int
    player_id: int
    position: str | None = Field(
        default=None, description="Место в турнире, может быть диапазоном — «17-32»"
    )
    points: int | None = Field(default=None, description="Начисленные рейтинговые очки")
