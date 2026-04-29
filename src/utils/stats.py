from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.schemas.nba_schemas import GameLogSchema

TREND_THRESHOLD = 1.0
POINTS_WEIGHT = 0.85
REBOUNDS_WEIGHT = 0.6
ASSISTS_WEIGHT = 0.7
SHOT_VOLUME_BONUS_WEIGHT = 0.12
FIELD_GOAL_MADE_WEIGHT = 0.45
THREE_POINTER_MADE_WEIGHT = 0.35
FREE_THROW_MADE_WEIGHT = 0.2
FIELD_GOAL_MISS_WEIGHT = 0.3
FREE_THROW_MISS_WEIGHT = 0.15


def parse_minutes(min_str: str) -> float:
    """Convert MIN field to float minutes. Handles '34:30', '34.5', '34'."""
    s = str(min_str).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            return int(parts[0]) + int(parts[1]) / 60
        except (ValueError, IndexError):
            return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def rounded(value: float) -> float:
    return round(value, 1)


def safe_average(values: list[float]) -> float:
    if not values:
        return 0.0
    return rounded(sum(values) / len(values))


def calc_stat_averages(logs: list["GameLogSchema"]) -> dict[str, float]:
    if not logs:
        return {
            "points": 0.0,
            "rebounds": 0.0,
            "assists": 0.0,
            "minutes": 0.0,
            "field_goals_made": 0.0,
            "field_goals_attempted": 0.0,
            "three_pointers_made": 0.0,
            "three_pointers_attempted": 0.0,
            "free_throws_made": 0.0,
            "free_throws_attempted": 0.0,
        }
    return {
        "points": safe_average([float(g.points) for g in logs]),
        "rebounds": safe_average([float(g.rebounds) for g in logs]),
        "assists": safe_average([float(g.assists) for g in logs]),
        "minutes": safe_average([parse_minutes(g.minutes) for g in logs]),
        "field_goals_made": safe_average([float(g.field_goals_made) for g in logs]),
        "field_goals_attempted": safe_average([float(g.field_goals_attempted) for g in logs]),
        "three_pointers_made": safe_average([float(g.three_pointers_made) for g in logs]),
        "three_pointers_attempted": safe_average([float(g.three_pointers_attempted) for g in logs]),
        "free_throws_made": safe_average([float(g.free_throws_made) for g in logs]),
        "free_throws_attempted": safe_average([float(g.free_throws_attempted) for g in logs]),
    }


def calc_trend_status(last5_pts: float, season_pts: float) -> str:
    diff = last5_pts - season_pts
    if diff > TREND_THRESHOLD:
        return "above_average"
    if diff < -TREND_THRESHOLD:
        return "below_average"
    return "stable"


def calc_shooting_impact(
    field_goals_made_diff: float,
    field_goals_attempted_diff: float,
    three_pointers_made_diff: float,
    free_throws_made_diff: float,
    field_goal_misses_diff: float,
    free_throw_misses_diff: float,
) -> float:
    return rounded(
        field_goals_made_diff * FIELD_GOAL_MADE_WEIGHT
        + max(field_goals_attempted_diff, 0.0) * SHOT_VOLUME_BONUS_WEIGHT
        + three_pointers_made_diff * THREE_POINTER_MADE_WEIGHT
        + free_throws_made_diff * FREE_THROW_MADE_WEIGHT
        - field_goal_misses_diff * FIELD_GOAL_MISS_WEIGHT
        - free_throw_misses_diff * FREE_THROW_MISS_WEIGHT
    )


def calc_player_score(
    points_diff: float,
    rebounds_diff: float,
    assists_diff: float,
    shooting_impact: float,
) -> float:
    box_score_component = (
        points_diff * POINTS_WEIGHT
        + rebounds_diff * REBOUNDS_WEIGHT
        + assists_diff * ASSISTS_WEIGHT
    )
    return rounded(box_score_component + shooting_impact)


def calc_player_status(score: float) -> str:
    if score >= 5:
        return "hot"
    if score >= 2:
        return "above_average"
    if score > -2:
        return "normal"
    if score > -5:
        return "below_average"
    return "cold"
