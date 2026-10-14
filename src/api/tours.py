from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import TourCreate, TourRead
from src.models import Tours
from src.models.base import get_session
from src.tasks import fill_empty_tours

router = APIRouter(prefix="/tours", tags=["tours"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=TourRead, status_code=status.HTTP_201_CREATED)
async def create_tour(
    payload: TourCreate,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> Tours:
    """Создать турнир по его id.

    Запись создаётся пустой, остальные поля дозаполняет фоновая задача.
    """
    exists = await session.scalar(select(Tours).where(Tours.id == payload.id))
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Турнир {payload.id} уже существует",
        )

    tour = Tours(id=payload.id)
    session.add(tour)
    await session.commit()
    await session.refresh(tour)

    background_tasks.add_task(fill_empty_tours)
    return tour
