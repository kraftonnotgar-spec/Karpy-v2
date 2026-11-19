"""Copyright lines that never go stale: saved text always shows the current year."""
from datetime import datetime, timezone
import re

_LAST_YEAR = re.compile(r"\b(?:19|20)\d{2}\b(?!.*\b(?:19|20)\d{2}\b)")


def with_current_year(text: str, now: datetime | None = None) -> str:
    """Fill "{year}", otherwise replace the written year (or the end of a range) with this year."""
    year = str((now or datetime.now(timezone.utc)).year)
    if "{year}" in text:
        return text.replace("{year}", year)
    return _LAST_YEAR.sub(year, text, count=1)
