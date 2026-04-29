from pydantic import BaseModel
from typing import Optional


class PlayerSchema(BaseModel):
    id: int
    full_name: str
    first_name: str
    last_name: str
    is_active: bool


class GameLogSchema(BaseModel):
    game_id: str
    game_date: str
    matchup: str
    minutes: str
    points: int
    rebounds: int
    assists: int
    field_goals_made: int
    field_goals_attempted: int
    three_pointers_made: int
    three_pointers_attempted: int
    free_throws_made: int
    free_throws_attempted: int


class PlayByPlayEventSchema(BaseModel):
    period: int
    clock: str
    event_type: str
    player_name: Optional[str]
    description_home: Optional[str]
    description_visitor: Optional[str]
    score: Optional[str]


class PointsByPeriodSchema(BaseModel):
    player_id: int
    game_id: str
    points_by_period: dict[str, int]
    total_points: int
