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
