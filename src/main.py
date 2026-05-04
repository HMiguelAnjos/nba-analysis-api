import logging
from contextlib import asynccontextmanager
from datetime import datetime

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
    LiveGamesCachedResponseSchema,
    LivePlayerComparisonSchema,
    TodayGamesSchema,
)
from src.schemas.nba_schemas import (
    GameLogSchema,
    PlayByPlayEventSchema,
    PlayerSchema,
    PointsByPeriodSchema,
)
from src.cache.live_games_cache import InMemoryLiveGamesCache
from src.config import ALLOWED_ORIGINS, ENABLE_LIVE_WORKER, LIVE_POLL_INTERVAL_MS, STATS_PROXY
from src.services.anomaly_service import AnomalyService
from src.services.live_analysis_service import LiveAnalysisService
from src.services.live_game_service import LiveGameService
from src.services.nba_service import NbaService
from src.services.player_analysis_service import PlayerAnalysisService
from src.workers.live_games_worker import start_live_games_worker
from src.workers.season_cache_warmer import start_season_cache_warmer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ------------------------------------------------------------------ #
# Shared instances                                                    #
# ------------------------------------------------------------------ #

nba = NbaService()
analysis = PlayerAnalysisService(nba)
live_game = LiveGameService()
live_analysis = LiveAnalysisService(live_game, analysis)
anomaly = AnomalyService()
live_cache = InMemoryLiveGamesCache()

MAX_LAST_GAMES = 20
DEFAULT_SEASON = "2024-25"


def _current_season() -> str:
    """NBA season runs Oct→Jun. Returns format 'YYYY-YY' (e.g. '2025-26')."""
    now = datetime.now()
    if now.month >= 10:
        return f"{now.year}-{str(now.year + 1)[-2:]}"
    return f"{now.year - 1}-{str(now.year)[-2:]}"


# ------------------------------------------------------------------ #
# App lifespan (startup / shutdown)                                   #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    if ENABLE_LIVE_WORKER:
        await start_live_games_worker(
            cache=live_cache,
            fetch_fn=live_game.fetch_scoreboard,
            interval_ms=LIVE_POLL_INTERVAL_MS,
        )
        # Pre-warm season averages so user requests don't depend on
        # stats.nba.com being available right that second.
        await start_season_cache_warmer(
            live_cache=live_cache,
            live_game=live_game,
            live_analysis=live_analysis,
            season=_current_season(),
        )
    else:
        logging.getLogger(__name__).info("Live games worker disabled (ENABLE_LIVE_WORKER=false).")
    yield


app = FastAPI(
    title="NBA Analysis API",
    description="Estatísticas da NBA para inteligência de apostas",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Aceita qualquer subdomínio do Railway (front em produção,
    # PR previews, etc.) sem precisar atualizar a env var manualmente.
    # *.up.railway.app cobre os deploys gerados; *.railway.app cobre
    # domínios custom mais curtos. Vercel também incluído por garantia.
    allow_origin_regex=r"https://.*\.(up\.)?railway\.app|https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/debug/server-ip")
def server_ip():
    """Retorna o IP público do servidor (Railway). Use para configurar whitelist de proxy."""
    import requests as req
    try:
        r = req.get("https://api.ipify.org?format=json", timeout=5)
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/debug/proxy-test")
def proxy_test():
    """Testa o proxy em HTTP e HTTPS separadamente para diagnosticar problemas de tunneling."""
    import requests as req
    proxies = {"http": STATS_PROXY, "https": STATS_PROXY} if STATS_PROXY else None
    results = {"proxy_configured": bool(STATS_PROXY)}

    # Teste 1: HTTP simples pelo proxy (sem CONNECT tunneling)
    try:
        r = req.get("http://httpbin.org/ip", proxies=proxies, timeout=10, verify=False)
        results["http_test"] = {"status": r.status_code, "body": r.json()}
    except Exception as exc:
        results["http_test"] = {"error": type(exc).__name__, "detail": str(exc)}

    # Teste 2: HTTPS pelo proxy (requer CONNECT tunneling)
    try:
        r = req.get("https://httpbin.org/ip", proxies=proxies, timeout=10, verify=False)
        results["https_test"] = {"status": r.status_code, "body": r.json()}
    except Exception as exc:
        results["https_test"] = {"error": type(exc).__name__, "detail": str(exc)}

    return results


@app.get("/debug/nba-stats")
def debug_nba_stats():
    """
    Quick diagnostic: hits stats.nba.com directly with browser-like headers.

    Use this to confirm whether the current host (e.g. Railway) is being
    blocked. If status != 200 here but works locally, stats.nba.com is
    blocking the cloud IP — set STATS_PROXY to route through a residential
    proxy.
    """
    import time
    import requests

    url = "https://stats.nba.com/stats/playergamelog"
    params = {"PlayerID": "2544", "Season": "2024-25", "SeasonType": "Regular Season"}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "x-nba-stats-origin": "stats",
        "x-nba-stats-token": "true",
    }
    proxies = {"http": STATS_PROXY, "https": STATS_PROXY} if STATS_PROXY else None

    # ScraperAPI terminates TLS itself — must skip cert verification.
    # Other proxies (Webshare residential, etc.) use CONNECT tunneling
    # and work fine with normal SSL verification.
    verify_ssl = not (STATS_PROXY and "scraperapi" in STATS_PROXY.lower())

    started = time.monotonic()
    try:
        r = requests.get(
            url, params=params, headers=headers, proxies=proxies,
            timeout=15, verify=verify_ssl,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "status": r.status_code,
            "elapsed_ms": elapsed_ms,
            "via_proxy": bool(STATS_PROXY),
            "ssl_verified": verify_ssl,
            "body_preview": r.text[:300],
        }
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "status": "error",
            "elapsed_ms": elapsed_ms,
            "via_proxy": bool(STATS_PROXY),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


@app.get("/live/cache/status")
def cache_status():
    """
    Estado atual do cache de jogos ao vivo.

    Retorna metadados do último snapshot gravado pelo worker:
    updated_at, age_ms, quantidade de jogos em cache.
    """
    snapshot = live_cache.get_snapshot()
    if snapshot is None:
        return {
            "status": "initializing",
            "last_update": None,
            "games_cached": 0,
            "age_ms": None,
        }
    return {
        "status": "running",
        "last_update": snapshot.updated_at.isoformat(),
        "games_cached": len(snapshot.data.games),
        "age_ms": snapshot.age_ms,
    }


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

@app.get("/games/live/today", response_model=LiveGamesCachedResponseSchema)
def today_games():
    snapshot = live_cache.get_snapshot()
    if snapshot is None:
        raise HTTPException(
            status_code=503,
            detail="Live games data not ready yet. Worker is initializing, try again in a moment.",
        )
    return LiveGamesCachedResponseSchema(
        date=snapshot.data.date,
        games=snapshot.data.games,
        updated_at=snapshot.updated_at.isoformat(),
        age_ms=snapshot.age_ms,
    )


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
    limit: int = Query(5, ge=1, le=50, description="Quantidade de jogadores no ranking"),
    consider_blowout: bool | None = Query(
        None,
        description=(
            "Considerar ajuste de blowout na projeção. "
            "Padrão: auto-detecta (playoffs=False, resto=True). "
            "Use True/False para forçar."
        ),
    ),
):
    try:
        return live_analysis.get_hot_ranking(
            game_id, season, limit, consider_blowout=consider_blowout
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao gerar hot ranking: {exc}")
