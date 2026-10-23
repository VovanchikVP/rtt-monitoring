from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class TourCreate(BaseModel):
    """Тело запроса на добавление турнира — только идентификатор."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0, description="ID турнира в РТТ")


class TourRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None
    location: str | None = None
    begin_date: date | None = None
    end_date: date | None = None


class TourListRead(TourRead):
    """Турнир в общем списке — с числом участников."""

    players_count: int = Field(default=0, description="Участников в базе")


class TourPageRead(BaseModel):
    """Страница списка турниров: сами турниры и сколько их всего."""

    items: list[TourListRead] = Field(default_factory=list, description="Турниры страницы")
    total: int = Field(default=0, description="Всего турниров в выборке")


class MatchesRefreshRead(BaseModel):
    """Результат постановки задач на обновление матчей."""

    tours: int = Field(description="Турниров в базе")
    queued: int = Field(description="Поставлено задач — по одной на турнир")


class TourPlayerRead(BaseModel):
    """Участник турнира в итоговом списке."""

    number: int = Field(description="Порядковый номер в списке")
    id: int
    name: str | None = None
    age: int | None = Field(default=None, description="Полных лет")
    city: str | None = None
    points: int = Field(default=0, description="Текущие рейтинговые очки")
