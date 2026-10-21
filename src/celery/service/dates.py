from datetime import date

# API отдаёт эту дату как признак «значение не заполнено»
EMPTY_DATE = "1900-01-01"


def parse_date(value: str | None) -> date | None:
    """Дата из ответа API; пустые значения и заглушки превращаются в None."""
    if not value or value.startswith(EMPTY_DATE):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
