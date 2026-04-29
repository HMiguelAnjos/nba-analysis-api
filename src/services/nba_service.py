import logging
import time
from typing import Any, Callable

import pandas as pd
from nba_api.stats.endpoints import PlayerGameLog, PlayByPlayV3
from nba_api.stats.static import players

from src.schemas.nba_schemas import (
    GameLogSchema,
    PlayerSchema,
    PlayByPlayEventSchema,
    PointsByPeriodSchema,
)
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


def _with_retry(fn: Callable, *args, **kwargs) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            logger.warning("Attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    raise last_error


def _fetch_pbp_df(game_id: str) -> pd.DataFrame:
    def _fetch():
        return PlayByPlayV3(
            game_id=game_id,
            timeout=DEFAULT_TIMEOUT,
        ).get_data_frames()[0]

    return _with_retry(_fetch)


class NbaService:
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

    def get_player_gamelog(self, player_id: int, season: str) -> list[GameLogSchema]:
        logger.info("Fetching game log for player %d, season %s", player_id, season)

        def _fetch():
            return PlayerGameLog(
                player_id=player_id,
                season=season,
                timeout=DEFAULT_TIMEOUT,
            ).get_data_frames()[0]

        df: pd.DataFrame = _with_retry(_fetch)

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
