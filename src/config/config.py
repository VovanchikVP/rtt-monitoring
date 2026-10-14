import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    DB_USER: str = os.environ.get("APP_DB_USER")
    DB_PASSWORD: str = os.environ.get("APP_DB_PASSWORD")
    DB_HOST: str = os.environ.get("APP_DB_HOST")
    DB_NAME: str = os.environ.get("APP_DB_NAME")


settings = Settings()
