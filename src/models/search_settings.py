from sqlalchemy import CheckConstraint, Column, Integer
from sqlalchemy.dialects.postgresql import ARRAY

from src.models.base import Base


class SearchSettings(Base):
    """Параметры автоматического поиска турниров.

    Таблица-одиночка: ровно одна строка с `id = 1`, значения в которой можно менять.
    Внешнее API фильтрует только по одному рангу и одной локации за запрос,
    поэтому по спискам `tour_ranks` и `location_ids` поиск идёт перебором;
    пустой список означает, что по этому полю фильтра нет.
    """

    __tablename__ = "search_settings"
    # вторую строку завести нельзя — настройки поиска всегда одни
    __table_args__ = (CheckConstraint("id = 1", name="ck_search_settings_single_row"),)

    # фиксированный идентификатор единственной строки
    ROW_ID = 1

    id = Column(Integer, primary_key=True, default=ROW_ID)
    # глубина периода поиска от текущей даты, месяцы
    period_months = Column(Integer, nullable=False, default=3)
    # размер страницы выдачи внешнего API
    per_page = Column(Integer, nullable=False, default=10)
    # ранги турниров
    tour_ranks = Column(ARRAY(Integer), nullable=False, default=[226])
    # пол участников
    tour_gender = Column(Integer, nullable=False, default=2)
    # места проведения
    location_ids = Column(ARRAY(Integer), nullable=False, default=[1419])
    # возрастные группы участников
    age_groups = Column(ARRAY(Integer), nullable=False, default=[131, 132])
