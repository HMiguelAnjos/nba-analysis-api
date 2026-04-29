import re
from typing import Any

# EVENTMSGTYPE codes from nba_api play-by-play
EVENT_TYPE_MAP = {
    1: "Field Goal Made",
    2: "Field Goal Missed",
    3: "Free Throw",
    4: "Rebound",
    5: "Turnover",
    6: "Foul",
    7: "Violation",
    8: "Substitution",
    9: "Timeout",
    10: "Jump Ball",
    12: "Start Period",
    13: "End Period",
}

FIELD_GOAL_MADE = 1
FREE_THROW = 3


def safe_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def is_three_pointer(description: str) -> bool:
    return "3PT" in description.upper()


def is_free_throw_made(description: str) -> bool:
    desc = description.upper()
    return "MISS" not in desc and "FREE THROW" in desc


def points_from_event(event_type: int, description: str) -> int:
    if event_type == FIELD_GOAL_MADE:
        return 3 if is_three_pointer(description) else 2
    if event_type == FREE_THROW and is_free_throw_made(description):
        return 1
    return 0


def normalize_player_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()
