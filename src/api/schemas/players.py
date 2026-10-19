from pydantic import BaseModel, Field


class RatingRefreshRead(BaseModel):
    """Результат постановки задач на обновление рейтинга."""

    players: int = Field(description="Игроков в базе")
    queued: int = Field(description="Поставлено задач — по одной на игрока")
    months: int = Field(description="Глубина истории рейтинга, месяцы")
