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
    # ISO 8601 UTC do início agendado do jogo (ex: "2026-05-04T23:00:00Z").
    # O front converte pro timezone local do usuário no display.
    game_time_utc: str | None = None
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
    is_starter: bool
    minutes: float
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
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
    is_starter: bool
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


class FairLineSchema(BaseModel):
    """
    Linha estimada (synthetic bookmaker) pra um mercado específico.

    `line` é a linha que estimamos que um bookmaker abriria.
    `edge` é (nossa_projeção_fim_de_jogo − line) — positivo = OVER tem
    valor; negativo = UNDER tem valor.
    `decision` é o resumo de strategy a partir do edge:
      STRONG_OVER (>=+2) | LEAN_OVER (>=+1) |
      NEUTRAL (-1<edge<+1) |
      LEAN_UNDER (<=-1) | STRONG_UNDER (<=-2).
    """
    line: float
    edge: float
    decision: Literal[
        "STRONG_OVER", "LEAN_OVER", "NEUTRAL", "LEAN_UNDER", "STRONG_UNDER"
    ]


class BlowoutRiskSchema(BaseModel):
    """
    Probabilidade estimada de garbage time (titulares saindo, banco assumindo).
    Calculado a partir do contexto do placar + período + tempo restante.
    `final` é estado especial para jogos encerrados (não há "risco" futuro).
    """
    percentage: int                                                # 0–100
    level: Literal["low", "medium", "high", "final"]
    reason: str                                                    # explicação curta


class PlayerBlowoutImpactSchema(BaseModel):
    """
    IMPACTO do blowout sobre um JOGADOR específico.
    Diferente do risco do jogo: aqui dizemos se ESTE jogador tende a perder
    minutos. Reservas de fim de banco normalmente NÃO recebem impacto
    (eles ganham minutos no garbage time). Titulares e jogadores de alta
    minutagem recebem.
    """
    applies: bool                                                  # True → mostrar flag
    level: Literal["low", "medium", "high"]
    reason: str


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
    # Médias recentes — base para o synthetic fair line.
    last_5_points: float
    last_5_rebounds: float
    last_5_assists: float
    last_10_points: float
    last_10_rebounds: float
    last_10_assists: float
    # Linha estimada (synthetic bookmaker) + edge da nossa projeção.
    # Substitui o sinal puro de "atual vs esperado" por algo ancorado
    # na linha provável do mercado.
    fair_line_points: FairLineSchema
    fair_line_rebounds: FairLineSchema
    fair_line_assists: FairLineSchema
    # Contexto que altera a projeção (ajustes já aplicados em pace_projection_*)
    fouls: int
    foul_trouble: bool          # 4+ faltas com risco real de banco
    blowout_risk: bool          # DEPRECATED: use blowout_impact.applies; mantido pra compat
    blowout_impact: PlayerBlowoutImpactSchema | None  # None = não mostrar flag
    on_court: bool              # se está em quadra AGORA (vs descansando no banco)
    is_starter: bool            # titular (campo `starter` da NBA Live API)
    shooting_impact: float
    status: str
    score: float


class HotRankingSchema(BaseModel):
    game_id: str
    limit: int
    ranking: list[HotRankingPlayerSchema]
    # Estado do jogo no momento do request — front usa pra renderizar
    # placar/relógio sem precisar refazer chamada ao scoreboard.
    game_status: str                                               # not_started | in_progress | final
    period: int
    clock: str
    home_score: int
    away_score: int
    blowout_risk: BlowoutRiskSchema
    updated_at: str                                                # ISO 8601 UTC do snapshot


# ------------------------------------------------------------------ #
# Live games cached response                                          #
# ------------------------------------------------------------------ #

class LiveGamesCachedResponseSchema(BaseModel):
    date: str
    games: list[LiveGameSchema]
    updated_at: str          # ISO 8601 UTC
    age_ms: int              # milliseconds since last worker update
    source: Literal["cache"] = "cache"


# ------------------------------------------------------------------ #
# Lineups (titulares/reservas + foto + nota de desempenho)            #
# ------------------------------------------------------------------ #
# Diferente do LivePlayerStatsSchema (que filtra quem não jogou e foca
# em produzir análise), este schema mostra o ELENCO COMPLETO do time —
# inclusive jogadores inativos, ainda no banco com 0 minutos, etc.
# Todos os flags vêm direto da NBA Live API (oficial), sem inferência.

class LineupPlayerSchema(BaseModel):
    player_id: int
    name: str
    jersey_num: str
    position: str                    # "PG", "SG", "SF", "PF", "C" ou ""
    is_starter: bool                 # NBA: player.starter == "1"
    is_on_court: bool                # NBA: player.oncourt == "1"
    played: bool                     # NBA: player.played == "1"
    status: str                      # "ACTIVE" | "INACTIVE"
    not_playing_reason: str | None
    photo_url: str                   # CDN da NBA, sempre 200 (fallback silhueta)
    minutes: float
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    field_goals_made: int
    field_goals_attempted: int
    three_pointers_made: int
    three_pointers_attempted: int
    free_throws_made: int
    free_throws_attempted: int
    plus_minus: int
    performance_rating: float        # 0–10
    performance_label: str           # Excelente | Bom | Regular | Ruim | N/A
    low_confidence: bool             # True se <10 min jogados
    blowout_impact: PlayerBlowoutImpactSchema | None  # None = sem flag


class LineupTeamSchema(BaseModel):
    team_id: int
    name: str
    tricode: str
    score: int
    starters: list[LineupPlayerSchema]      # 5 jogadores titulares
    bench: list[LineupPlayerSchema]         # reservas (jogaram OU no banco)
    inactive: list[LineupPlayerSchema]      # status == INACTIVE


class LineupGameSchema(BaseModel):
    game_id: str
    game_status: str
    period: int
    clock: str
    home_team: LineupTeamSchema
    away_team: LineupTeamSchema
    blowout_risk: BlowoutRiskSchema
    updated_at: str                                                # ISO 8601 UTC
