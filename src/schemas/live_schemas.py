from typing import Literal
from pydantic import BaseModel


class LiveTeamSchema(BaseModel):
    team_id: int
    name: str
    tricode: str
    score: int


class LiveGameSchema(BaseModel):
    game_id: str
    game_status: str
    period: int
    clock: str
    home_team: LiveTeamSchema
    away_team: LiveTeamSchema


class TodayGamesSchema(BaseModel):
    date: str
    games: list[LiveGameSchema]


# ------------------------------------------------------------------ #
# Boxscore                                                            #
# ------------------------------------------------------------------ #

class LivePlayerStatsSchema(BaseModel):
    player_id: int
    name: str
    position: str
    minutes: float
    points: int
    rebounds: int
    assists: int
    field_goals_made: int
    field_goals_attempted: int
    three_pointers_made: int
    three_pointers_attempted: int
    free_throws_made: int
    free_throws_attempted: int
    plus_minus: int
    fouls: int
    on_court: bool


class LiveTeamBoxscoreSchema(BaseModel):
    team_id: int
    name: str
    tricode: str
    score: int
    players: list[LivePlayerStatsSchema]


class LiveBoxscoreSchema(BaseModel):
    game_id: str
    game_status: str
    period: int
    clock: str
    home_team: LiveTeamBoxscoreSchema
    away_team: LiveTeamBoxscoreSchema


# ------------------------------------------------------------------ #
# Live analysis                                                       #
# ------------------------------------------------------------------ #

class LiveCurrentStatsSchema(BaseModel):
    points: int
    rebounds: int
    assists: int
    field_goals_made: int
    field_goals_attempted: int
    three_pointers_made: int
    three_pointers_attempted: int
    free_throws_made: int
    free_throws_attempted: int


class LiveSeasonAverageSchema(BaseModel):
    points: float
    rebounds: float
    assists: float
    minutes: float
    field_goals_made: float
    field_goals_attempted: float
    three_pointers_made: float
    three_pointers_attempted: float
    free_throws_made: float
    free_throws_attempted: float


class LiveExpectedStatsSchema(BaseModel):
    points: float
    rebounds: float
    assists: float
    field_goals_made: float
    field_goals_attempted: float
    three_pointers_made: float
    three_pointers_attempted: float
    free_throws_made: float
    free_throws_attempted: float


class LiveDifferenceSchema(BaseModel):
    points: float
    rebounds: float
    assists: float
    field_goals_made: float
    field_goals_attempted: float
    three_pointers_made: float
    three_pointers_attempted: float
    free_throws_made: float
    free_throws_attempted: float


class LivePlayerAnalysisSchema(BaseModel):
    player_id: int
    name: str
    team: str
    minutes: float
    fouls: int
    on_court: bool
    current: LiveCurrentStatsSchema
    season_average: LiveSeasonAverageSchema
    expected_until_now: LiveExpectedStatsSchema
    difference: LiveDifferenceSchema
    shooting_impact: float
    status: str
    score: float


class LiveAnalysisErrorSchema(BaseModel):
    player_id: int
    name: str
    reason: str


class LiveGameAnalysisSchema(BaseModel):
    game_id: str
    season: str
    game_status: str
    period: int
    clock: str
    analysis_type: str
    players: list[LivePlayerAnalysisSchema]
    hot_players: list[LivePlayerAnalysisSchema]
    cold_players: list[LivePlayerAnalysisSchema]
    errors: list[LiveAnalysisErrorSchema]


class LivePlayerComparisonSchema(BaseModel):
    player_id: int
    game_id: str
    name: str
    team: str
    minutes: float
    current: LiveCurrentStatsSchema
    season_average: LiveSeasonAverageSchema
    expected_until_now: LiveExpectedStatsSchema
    difference: LiveDifferenceSchema
    shooting_impact: float
    status: str
    analysis_type: str


# ------------------------------------------------------------------ #
# Hot ranking                                                         #
# ------------------------------------------------------------------ #

class PaceProjectionSchema(BaseModel):
    """Projeção até o fim do jogo com margem de erro."""
    low: float
    expected: float
    high: float


class HotRankingPlayerSchema(BaseModel):
    player_id: int
    name: str
    team: str
    minutes: float
    current_points: int
    current_assists: int
    current_rebounds: int
    expected_points: float
    expected_assists: float
    expected_rebounds: float
    points_diff: float
    assists_diff: float
    rebounds_diff: float
    # Projeção BASE blended (mantida para compatibilidade — ritmo atual + temporada)
    projected_points: float
    projected_assists: float
    projected_rebounds: float
    # Projeção até o fim do jogo com margem de erro (peso alto no ritmo atual)
    pace_projection_points: PaceProjectionSchema
    pace_projection_assists: PaceProjectionSchema
    pace_projection_rebounds: PaceProjectionSchema
    # Contexto que altera a projeção (ajustes já aplicados em pace_projection_*)
    fouls: int
    foul_trouble: bool          # 4+ faltas com risco real de banco
    blowout_risk: bool          # placar aberto, estrela tende a sentar
    on_court: bool              # se está em quadra AGORA (vs descansando no banco)
    shooting_impact: float
    status: str
    score: float


class HotRankingSchema(BaseModel):
    game_id: str
    limit: int
    ranking: list[HotRankingPlayerSchema]


# ------------------------------------------------------------------ #
# Live games cached response                                          #
# ------------------------------------------------------------------ #

class LiveGamesCachedResponseSchema(BaseModel):
    date: str
    games: list[LiveGameSchema]
    updated_at: str          # ISO 8601 UTC
    age_ms: int              # milliseconds since last worker update
    source: Literal["cache"] = "cache"
