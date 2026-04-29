import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from src.schemas.analysis_schemas import (
    DashboardSchema,
    GameStatSchema,
    PointsByPeriodAverageSchema,
    SeasonAnalysisSchema,
)
from src.schemas.live_schemas import (
    HotRankingSchema,
    LiveBoxscoreSchema,
    LiveGameAnalysisSchema,
    LivePlayerComparisonSchema,
    TodayGamesSchema,
)
from src.schemas.nba_schemas import (
    GameLogSchema,
    PlayByPlayEventSchema,
    PlayerSchema,
    PointsByPeriodSchema,
)
from src.config import ALLOWED_ORIGINS
from src.services.live_analysis_service import LiveAnalysisService
from src.services.live_game_service import LiveGameService
from src.services.nba_service import NbaService
from src.services.player_analysis_service import PlayerAnalysisService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="NBA Analysis API",
    description="Estatísticas da NBA para inteligência de apostas",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

nba = NbaService()
analysis = PlayerAnalysisService(nba)
live_game = LiveGameService()
live_analysis = LiveAnalysisService(live_game, analysis)

MAX_LAST_GAMES = 20
DEFAULT_SEASON = "2024-25"


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _season_query(default: str = DEFAULT_SEASON) -> str:
    return Query(default, description="Temporada no formato YYYY-YY, ex: 2024-25")


def _last_games_query() -> int:
    return Query(
        10,
        ge=1,
        le=MAX_LAST_GAMES,
        description=f"Número de jogos a analisar (máx: {MAX_LAST_GAMES})",
    )


# ------------------------------------------------------------------ #
# Basic routes                                                        #
# ------------------------------------------------------------------ #

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/players/search", response_model=list[PlayerSchema])
def search_players(name: str = Query(..., min_length=2, description="Nome do jogador")):
    try:
        results = nba.search_players(name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao buscar jogadores: {exc}")
    if not results:
        raise HTTPException(status_code=404, detail=f"Nenhum jogador encontrado para '{name}'.")
    return results


@app.get("/players/{player_id}/gamelog", response_model=list[GameLogSchema])
def player_gamelog(
    player_id: int,
    season: str = _season_query(),
):
    try:
        logs = nba.get_player_gamelog(player_id, season)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao buscar game log: {exc}")
    if not logs:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum jogo encontrado para player_id={player_id} na temporada {season}.",
        )
    return logs


@app.get("/games/{game_id}/play-by-play", response_model=list[PlayByPlayEventSchema])
def play_by_play(game_id: str):
    try:
        events = nba.get_play_by_play(game_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao buscar play-by-play: {exc}")
    if not events:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum evento encontrado para game_id={game_id}.",
        )
    return events


@app.get(
    "/players/{player_id}/games/{game_id}/points-by-period",
    response_model=PointsByPeriodSchema,
)
def points_by_period(player_id: int, game_id: str):
    try:
        result = nba.get_points_by_period(player_id, game_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao calcular pontos por período: {exc}")
    return result


# ------------------------------------------------------------------ #
# Analysis routes                                                     #
# ------------------------------------------------------------------ #

@app.get("/players/{player_id}/analysis/season", response_model=SeasonAnalysisSchema)
def season_analysis(
    player_id: int,
    season: str = _season_query(),
):
    try:
        return analysis.get_season_analysis(player_id, season)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao calcular análise da temporada: {exc}")


@app.get("/players/{player_id}/stats/games", response_model=list[GameStatSchema])
def game_stats(
    player_id: int,
    season: str = _season_query(),
):
    try:
        stats = analysis.get_game_stats(player_id, season)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao buscar estatísticas por jogo: {exc}")
    if not stats:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum jogo encontrado para player_id={player_id} na temporada {season}.",
        )
    return stats


@app.get(
    "/players/{player_id}/analysis/points-by-period",
    response_model=PointsByPeriodAverageSchema,
)
def points_by_period_average(
    player_id: int,
    season: str = _season_query(),
    last_games: int = _last_games_query(),
):
    try:
        return analysis.get_points_by_period_average(player_id, season, last_games)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Erro ao calcular média de pontos por período: {exc}",
        )


@app.get("/players/{player_id}/dashboard", response_model=DashboardSchema)
def dashboard(
    player_id: int,
    season: str = _season_query(),
    last_games: int = _last_games_query(),
):
    try:
        return analysis.get_dashboard(player_id, season, last_games)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao montar dashboard: {exc}")


# ------------------------------------------------------------------ #
# Live routes  (register /games/live/today BEFORE /games/{game_id}/…)#
# ------------------------------------------------------------------ #

@app.get("/games/live/today", response_model=TodayGamesSchema)
def today_games():
    try:
        return live_game.get_today_games()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/games/{game_id}/live-boxscore", response_model=LiveBoxscoreSchema)
def live_boxscore(game_id: str):
    try:
        return live_game.get_live_boxscore(game_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/games/{game_id}/live-analysis", response_model=LiveGameAnalysisSchema)
def live_game_analysis(
    game_id: str,
    season: str = _season_query(),
):
    try:
        return live_analysis.get_game_analysis(game_id, season)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro na análise live: {exc}")


@app.get(
    "/players/{player_id}/games/{game_id}/live-comparison",
    response_model=LivePlayerComparisonSchema,
)
def live_player_comparison(
    player_id: int,
    game_id: str,
    season: str = _season_query(),
):
    try:
        return live_analysis.get_player_live_comparison(player_id, game_id, season)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro na comparação live: {exc}")


@app.get("/games/{game_id}/live-hot-ranking", response_model=HotRankingSchema)
def live_hot_ranking(
    game_id: str,
    season: str = _season_query(),
    limit: int = Query(5, ge=1, le=20, description="Quantidade de jogadores no ranking"),
):
    try:
        return live_analysis.get_hot_ranking(game_id, season, limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao gerar hot ranking: {exc}")
