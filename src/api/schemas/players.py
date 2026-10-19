from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class RatingRefreshRead(BaseModel):
    """Результат постановки задач на обновление рейтинга."""

    players: int = Field(description="Игроков в базе")
    queued: int = Field(description="Поставлено задач — по одной на игрока")
    months: int = Field(description="Глубина истории рейтинга, месяцы")


class PlayerPointRead(BaseModel):
    """Одна запись истории рейтинга игрока."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    points: int
