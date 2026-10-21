import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MatchRead(BaseModel):
    """Матч турнира: соперники, победитель и счёт."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tour_id: int
    first_player_id: int
    second_player_id: int
    winner_player_id: int | None = Field(
        default=None, description="Победитель; None, пока матч не доигран"
    )
    first_score: int | None = Field(default=None, description="Выигранных сетов у первого игрока")
    second_score: int | None = Field(default=None, description="Выигранных сетов у второго игрока")
    score: str | None = Field(default=None, description="Счёт целиком — «6-4 3-6 7-5»")
    status: str | None = Field(default=None, description="Состояние матча")
    # datetime.date, а не date: поле с таким же именем затенило бы импорт типа
    date: datetime.date | None = Field(default=None, description="Дата матча")
