from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from src.config.config import settings

DATABASE_URL = f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}/{settings.DB_NAME}"

engine = create_async_engine(
    DATABASE_URL,
    max_overflow=20,
    pool_recycle=1800,
    pool_pre_ping=True,
    connect_args={
        "command_timeout": 20,
        "timeout": 20,
    },
)

Base = declarative_base()
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[Any, Any]:
    async with async_session() as session:
        yield session
