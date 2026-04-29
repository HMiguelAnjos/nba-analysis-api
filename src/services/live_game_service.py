import logging
from typing import Optional

from nba_api.live.nba.endpoints import boxscore, scoreboard

from src.schemas.live_schemas import (
    LiveBoxscoreSchema,
    LiveGameSchema,
    LivePlayerStatsSchema,
    LiveTeamBoxscoreSchema,
    LiveTeamSchema,
    TodayGamesSchema,
)
from src.utils.cache import SimpleCache
from src.utils.stats import rounded
from src.utils.time_utils import format_game_clock, map_game_status, parse_minutes_to_float

logger = logging.getLogger(__name__)

SCOREBOARD_TTL = 30   # seconds
BOXSCORE_TTL = 15     # seconds


def _parse_player(p: dict) -> Optional[LivePlayerStatsSchema]:
    stats = p.get("statistics", {})
    minutes = parse_minutes_to_float(stats.get("minutes", "PT00M00.00S"))
    if minutes <= 0:
        return None
    return LivePlayerStatsSchema(
        player_id=int(p.get("personId", 0)),
        name=p.get("name", ""),
        position=p.get("position", ""),
        minutes=rounded(minutes),
        points=int(stats.get("points", 0)),
        rebounds=int(stats.get("reboundsTotal", 0)),
        assists=int(stats.get("assists", 0)),
        field_goals_made=int(stats.get("fieldGoalsMade", 0)),
        field_goals_attempted=int(stats.get("fieldGoalsAttempted", 0)),
        three_pointers_made=int(stats.get("threePointersMade", 0)),
        three_pointers_attempted=int(stats.get("threePointersAttempted", 0)),
        free_throws_made=int(stats.get("freeThrowsMade", 0)),
        free_throws_attempted=int(stats.get("freeThrowsAttempted", 0)),
        plus_minus=int(stats.get("plusMinusPoints", 0)),
    )


def _parse_team_boxscore(team: dict) -> LiveTeamBoxscoreSchema:
    players = [
        parsed
        for p in team.get("players", [])
        if (parsed := _parse_player(p)) is not None
    ]
    city = team.get("teamCity", "")
    name = team.get("teamName", "")
    return LiveTeamBoxscoreSchema(
        team_id=int(team.get("teamId", 0)),
        name=f"{city} {name}".strip(),
        tricode=team.get("teamTricode", ""),
        score=int(team.get("score", 0)),
        players=players,
    )


class LiveGameService:
    def __init__(self) -> None:
        self._cache = SimpleCache()

    def get_today_games(self) -> TodayGamesSchema:
        cached = self._cache.get("scoreboard")
        if cached:
            logger.debug("Scoreboard served from cache")
            return cached

        logger.info("Fetching live scoreboard")
        try:
            board = scoreboard.ScoreBoard()
            data = board.get_dict()["scoreboard"]
        except Exception as exc:
            raise RuntimeError(f"Erro ao buscar scoreboard: {exc}") from exc

        games: list[LiveGameSchema] = []
        for g in data.get("games", []):
            home = g.get("homeTeam", {})
            away = g.get("awayTeam", {})
            games.append(
                LiveGameSchema(
                    game_id=g.get("gameId", ""),
                    game_status=map_game_status(g.get("gameStatus", 0)),
                    period=int(g.get("period", 0)),
                    clock=format_game_clock(g.get("gameClock", "")),
                    home_team=LiveTeamSchema(
                        team_id=int(home.get("teamId", 0)),
                        name=f"{home.get('teamCity', '')} {home.get('teamName', '')}".strip(),
                        tricode=home.get("teamTricode", ""),
                        score=int(home.get("score", 0)),
                    ),
                    away_team=LiveTeamSchema(
                        team_id=int(away.get("teamId", 0)),
                        name=f"{away.get('teamCity', '')} {away.get('teamName', '')}".strip(),
                        tricode=away.get("teamTricode", ""),
                        score=int(away.get("score", 0)),
                    ),
                )
            )

        result = TodayGamesSchema(date=data.get("gameDate", ""), games=games)
        self._cache.set("scoreboard", result, SCOREBOARD_TTL)
        logger.info("Scoreboard fetched: %d games", len(games))
        return result

    def get_live_boxscore(self, game_id: str) -> LiveBoxscoreSchema:
        cache_key = f"boxscore:{game_id}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.debug("Boxscore %s served from cache", game_id)
            return cached

        logger.info("Fetching live boxscore for game %s", game_id)
        try:
            bs = boxscore.BoxScore(game_id=game_id)
            game_data = bs.get_dict()["game"]
        except Exception as exc:
            raise RuntimeError(f"Erro ao buscar boxscore para {game_id}: {exc}") from exc

        result = LiveBoxscoreSchema(
            game_id=game_id,
            game_status=map_game_status(game_data.get("gameStatus", 0)),
            period=int(game_data.get("period", 0)),
            clock=format_game_clock(game_data.get("gameClock", "")),
            home_team=_parse_team_boxscore(game_data.get("homeTeam", {})),
            away_team=_parse_team_boxscore(game_data.get("awayTeam", {})),
        )
        self._cache.set(cache_key, result, BOXSCORE_TTL)
        return result
