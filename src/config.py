"""Project-wide paths and business constants.

Every business constant that affects money lives here, so the methodology
document and the code never drift apart.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
ANSWER_KEY_DIR = DATA_DIR / "answer_key"
SQL_DIR = ROOT / "sql"
PROMPTS_DIR = ROOT / "prompts"
LLM_CACHE_DIR = ROOT / "llm_cache"
DOCS_DIR = ROOT / "docs"
SITE_DATA_DIR = DOCS_DIR / "data"
PROJECT_DOCS_DIR = ROOT / "project_docs"

# Reconciliation period: five closed weeks, Monday 00:00 to Sunday 23:59:59,
# local time of Sao Paulo (timestamps are stored as naive local times).
PERIOD_START = date(2026, 9, 28)
N_WEEKS = 5
PAYMENT_OFFSET_DAYS = 3  # payout runs on the Wednesday after the week closes

# Tolerances used by the detection rules (integer cents).
TOLERANCE_LINE_CENTS = 2
TOLERANCE_REPASSE_CENTS = 10

# Bank matching window: a payout may settle from D+0 to D+2 after its due date.
BANK_DATE_WINDOW_DAYS = 2
# Minimum Jaro-Winkler similarity between a bank description and a registered
# name to consider the line a candidate for a restaurant.
BANK_NAME_SIMILARITY_MIN = 0.80
BANK_NAME_SIMILARITY_STRONG = 0.90

# LLM confidence below this threshold sends the case to human review.
REVIEW_CONFIDENCE_THRESHOLD = 0.75

MARKETPLACE_NAME = "Talher"

# Public addresses of the project (GitHub Pages and repository).
SITE_URL = "https://andreilud.github.io/conciliador-de-repasses"
REPO_URL = "https://github.com/AndreiLud/conciliador-de-repasses"


# Calendar read from the payout files (repasses.csv) when the engine runs; the
# constants above are the default used by the generator and before ingestion.
_CALENDAR: dict[str, tuple[date, date, date]] = {}


def set_calendar(rows: list[tuple[str, date, date, date]]) -> None:
    """rows: (week id, first day, last day, payment date), one per payout week."""
    _CALENDAR.clear()
    for wid, start, end, pay in sorted(rows):
        _CALENDAR[wid] = (start, end, pay)


def week_starts() -> list[date]:
    if _CALENDAR:
        return [v[0] for v in _CALENDAR.values()]
    return [PERIOD_START + timedelta(days=7 * i) for i in range(N_WEEKS)]


def week_id(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_bounds(wid: str) -> tuple[date, date]:
    if wid in _CALENDAR:
        return _CALENDAR[wid][0], _CALENDAR[wid][1]
    for start in week_starts():
        if week_id(start) == wid:
            return start, start + timedelta(days=6)
    raise KeyError(wid)


def payment_date(wid: str) -> date:
    if wid in _CALENDAR:
        return _CALENDAR[wid][2]
    _, end = week_bounds(wid)
    return end + timedelta(days=PAYMENT_OFFSET_DAYS)


def week_ids() -> list[str]:
    if _CALENDAR:
        return list(_CALENDAR)
    return [week_id(d) for d in week_starts()]


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default
