import logging
import time
from typing import Any, Callable

import pandas as pd
import requests
import urllib3
from nba_api.stats.endpoints import PlayerGameLog, PlayByPlayV3
from nba_api.stats.static import players

from src.config import STATS_PROXY


# When STATS_PROXY is configured (e.g. ScraperAPI), the proxy itself does
# its own TLS termination and presents a non-public certificate, so the
# client *must* skip verification. Without this, any HTTPS call through
# the proxy fails with SSLError (CERTIFICATE_VERIFY_FAILED). Patch is
# applied once at import time and only when a proxy is in use.
def _disable_ssl_verification_for_proxy() -> None:
    """Make every requests.Session.request default to verify=False.

    This affects all outbound HTTPS in this process, which is acceptable
    in our context: we don't accept user-controlled target URLs, and the
    cdn.nba.com paths still benefit from the proxy operator's TLS
    handling. The InsecureRequestWarning spam is silenced too.
    """
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    _orig_request = requests.Session.request

    def _patched_request(self, method, url, **kwargs):
        kwargs.setdefault("verify", False)
        return _orig_request(self, method, url, **kwargs)

    requests.Session.request = _patched_request


# ScraperAPI terminates TLS itself and presents its own certificate, so
# SSL verification must be disabled when routing through it. Other proxies
# (e.g. Webshare residential) use standard CONNECT tunneling and do NOT
# need this — applying it there breaks the connection.
_PROXY_NEEDS_SSL_BYPASS = STATS_PROXY and "scraperapi" in STATS_PROXY.lower()

if _PROXY_NEEDS_SSL_BYPASS:
    _disable_ssl_verification_for_proxy()
    logging.getLogger(__name__).info(
        "ScraperAPI proxy detected — SSL verification disabled."
    )
elif STATS_PROXY:
    logging.getLogger(__name__).info(
        "STATS_PROXY detected (non-ScraperAPI) — SSL verification kept enabled."
    )
from src.schemas.nba_schemas import (
    GameLogSchema,
    PlayerSchema,
    PlayByPlayEventSchema,
    PointsByPeriodSchema,
)
from src.utils.cache import PersistentCache
from src.utils.converters import (
    EVENT_TYPE_MAP,
    normalize_player_name,
    points_from_event,
    safe_str,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_DELAY = 5.0

# Timeout curto para contexto de análise ao vivo (parallel workers)
LIVE_TIMEOUT = 6
LIVE_MAX_RETRIES = 1

# Gamelogs barely change after a game ends; 24h is more than enough
# and gives huge resilience when stats.nba.com is blocking the host.
GAMELOG_TTL = 86_400


def _proxy_kwargs() -> dict:
    """Returns {'proxy': STATS_PROXY} when configured, else empty dict.

    nba_api's stats endpoints accept a `proxy` kwarg (a single URL string).
    On Railway/cloud, stats.nba.com routinely blocks datacenter IPs; routing
    via a residential proxy works around this. Set the STATS_PROXY env var
    (e.g. http://user:pass@host:port) to enable. If unset, calls go direct.
    """
    return {"proxy": STATS_PROXY} if STATS_PROXY else {}


# nba_api 1.5.x already sends Chrome User-Agent + Referer, but misses the
# NBA-specific tokens that nba.com's own frontend includes. Adding them makes
# the request indistinguishable from a real browser session on the site.
_ENHANCED_HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}


def _with_retry(fn: Callable, *args, max_retries: int = MAX_RETRIES, **kwargs) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            logger.warning("Attempt %d/%d failed: %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(RETRY_DELAY)
    raise last_error


def _fetch_pbp_df(game_id: str) -> pd.DataFrame:
    def _fetch():
        return PlayByPlayV3(
            game_id=game_id,
            timeout=DEFAULT_TIMEOUT,
            headers=_ENHANCED_HEADERS,
            **_proxy_kwargs(),
        ).get_data_frames()[0]

    return _with_retry(_fetch)


class NbaService:
    def __init__(self) -> None:
        # Persistent on-disk cache for player gamelogs. Survives container
        # restarts and means a single successful fetch unlocks the data for
        # 24 h regardless of stats.nba.com availability.
        self._gamelog_cache = PersistentCache(path="/tmp/nba_gamelog_cache.json")

    def search_players(self, name: str) -> list[PlayerSchema]:
        query = normalize_player_name(name)
        logger.info("Searching players with query: %s", query)

        all_players = players.get_players()
        matches = [
            p for p in all_players
            if query in normalize_player_name(p["full_name"])
        ]

        return [
            PlayerSchema(
                id=p["id"],
                full_name=p["full_name"],
                first_name=p["first_name"],
                last_name=p["last_name"],
                is_active=p["is_active"],
            )
            for p in matches
        ]

    def get_player_gamelog(
        self,
        player_id: int,
        season: str,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ) -> list[GameLogSchema]:
        cache_key = f"gamelog:{player_id}:{season}"
        cached = self._gamelog_cache.get(cache_key)
        if cached is not None:
            logger.info("Gamelog cache HIT for player %d, season %s", player_id, season)
            return [GameLogSchema(**g) for g in cached]

        logger.info("Gamelog cache MISS — fetching from stats.nba.com (player %d, season %s)", player_id, season)

        def _fetch():
            return PlayerGameLog(
                player_id=player_id,
                season=season,
                timeout=timeout,
                headers=_ENHANCED_HEADERS,
                **_proxy_kwargs(),
            ).get_data_frames()[0]

        df: pd.DataFrame = _with_retry(_fetch, max_retries=max_retries)

        if df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            results.append(
                GameLogSchema(
                    game_id=str(row["Game_ID"]),
                    game_date=str(row["GAME_DATE"]),
                    matchup=str(row["MATCHUP"]),
                    minutes=str(row["MIN"]),
                    points=int(row["PTS"]),
                    rebounds=int(row["REB"]),
                    assists=int(row["AST"]),
                    field_goals_made=int(row["FGM"]),
                    field_goals_attempted=int(row["FGA"]),
                    three_pointers_made=int(row["FG3M"]),
                    three_pointers_attempted=int(row["FG3A"]),
                    free_throws_made=int(row["FTM"]),
                    free_throws_attempted=int(row["FTA"]),
                )
            )

        # Persist for 24h so subsequent endpoints (analysis/season,
        # stats/games, dashboard, etc.) survive any stats.nba.com outage.
        if results:
            self._gamelog_cache.set(
                cache_key,
                [g.model_dump() for g in results],
                GAMELOG_TTL,
            )
            logger.info("Gamelog cached for player %d (%d games)", player_id, len(results))
        return results

    def get_play_by_play(self, game_id: str) -> list[PlayByPlayEventSchema]:
        logger.info("Fetching play-by-play for game %s", game_id)

        df = _fetch_pbp_df(game_id)

        if df.empty:
            return []

        events = []
        for _, row in df.iterrows():
            event_type_code = int(row.get("EVENTMSGTYPE", 0))
            event_type_label = EVENT_TYPE_MAP.get(event_type_code, str(event_type_code))

            player_name = safe_str(row.get("PLAYER1_NAME")) or None
            home_desc = safe_str(row.get("HOMEDESCRIPTION")) or None
            visitor_desc = safe_str(row.get("VISITORDESCRIPTION")) or None
            score = safe_str(row.get("SCORE")) or None

            events.append(
                PlayByPlayEventSchema(
                    period=int(row.get("PERIOD", 0)),
                    clock=safe_str(row.get("PCTIMESTRING")),
                    event_type=event_type_label,
                    player_name=player_name,
                    description_home=home_desc,
                    description_visitor=visitor_desc,
                    score=score,
                )
            )
        return events

    def get_points_by_period(self, player_id: int, game_id: str) -> PointsByPeriodSchema:
        logger.info("Calculating points by period for player %d in game %s", player_id, game_id)

        if not players.find_player_by_id(player_id):
            raise ValueError(f"Player with id {player_id} not found.")

        df = _fetch_pbp_df(game_id)

        points_by_period: dict[str, int] = {}

        for _, row in df.iterrows():
            # Match by player ID — more reliable than name matching
            p1_id = int(row.get("PLAYER1_ID", 0))
            if p1_id != player_id:
                continue

            event_type = int(row.get("EVENTMSGTYPE", 0))
            home_desc = safe_str(row.get("HOMEDESCRIPTION"))
            visitor_desc = safe_str(row.get("VISITORDESCRIPTION"))
            description = home_desc or visitor_desc

            pts = points_from_event(event_type, description)
            if pts == 0:
                continue

            period = str(int(row.get("PERIOD", 0)))
            points_by_period[period] = points_by_period.get(period, 0) + pts

        total = sum(points_by_period.values())

        return PointsByPeriodSchema(
            player_id=player_id,
            game_id=game_id,
            points_by_period=points_by_period,
            total_points=total,
        )
