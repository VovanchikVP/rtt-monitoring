import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    DB_USER: str = os.environ.get("APP_DB_USER")
    DB_PASSWORD: str = os.environ.get("APP_DB_PASSWORD")
    DB_HOST: str = os.environ.get("APP_DB_HOST")
    DB_NAME: str = os.environ.get("APP_DB_NAME")

    RABBITMQ_HOST: str = os.environ.get("APP_RABBITMQ_HOST", "localhost")
    RABBITMQ_PORT: int = int(os.environ.get("APP_RABBITMQ_PORT", 5672))
    RABBITMQ_USER: str = os.environ.get("APP_RABBITMQ_USER", "guest")
    RABBITMQ_PASSWORD: str = os.environ.get("APP_RABBITMQ_PASSWORD", "guest")
    RABBITMQ_VHOST: str = os.environ.get("APP_RABBITMQ_VHOST", "/")
    # как часто периодическая задача ищет незаполненные турниры, секунды
    FILL_TOURS_INTERVAL: int = int(os.environ.get("APP_FILL_TOURS_INTERVAL", 300))

    @property
    def CELERY_BROKER_URL(self) -> str:
        vhost = self.RABBITMQ_VHOST.lstrip("/")
        return (
            f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}"
            f"@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/{vhost}"
        )


settings = Settings()
