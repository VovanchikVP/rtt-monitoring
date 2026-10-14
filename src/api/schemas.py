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


class TourPlayerRead(BaseModel):
    """Участник турнира в итоговом списке."""

    number: int = Field(description="Порядковый номер в списке")
    id: int
    name: str | None = None
    age: int | None = Field(default=None, description="Полных лет")
    city: str | None = None
    points: int = Field(default=0, description="Текущие рейтинговые очки")
