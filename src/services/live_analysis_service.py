import logging
from typing import Optional

from src.schemas.live_schemas import (
    HotRankingPlayerSchema,
    HotRankingSchema,
    LiveAnalysisErrorSchema,
    LiveBoxscoreSchema,
    LiveCurrentStatsSchema,
    LiveDifferenceSchema,
    LiveExpectedStatsSchema,
    LiveGameAnalysisSchema,
    LivePlayerAnalysisSchema,
    LivePlayerComparisonSchema,
    LivePlayerStatsSchema,
    LiveSeasonAverageSchema,
)
from src.services.live_game_service import LiveGameService
from src.services.player_analysis_service import PlayerAnalysisService
from src.utils.cache import SimpleCache
from src.utils.stats import (
    calc_player_score,
    calc_player_status,
    calc_shooting_impact,
    rounded,
)

logger = logging.getLogger(__name__)

SEASON_AVG_TTL = 600       # 10 minutes
ANALYSIS_TYPE = "experimental_live_analysis"


class LiveAnalysisService:
    def __init__(
        self,
        live_game_service: LiveGameService,
        player_analysis_service: PlayerAnalysisService,
    ) -> None:
        self.live = live_game_service
        self.player_analysis = player_analysis_service
        self._cache = SimpleCache()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_season_averages(
        self, player_id: int, season: str
    ) -> Optional[dict[str, float]]:
        """Fetch and cache season averages for a player. Returns None on failure."""
        cache_key = f"season_avg:{player_id}:{season}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = self.player_analysis.get_season_analysis(player_id, season)
            avgs = {
                "points": result.averages.points,
                "rebounds": result.averages.rebounds,
                "assists": result.averages.assists,
                "minutes": result.averages.minutes,
                "field_goals_made": result.averages.field_goals_made,
                "field_goals_attempted": result.averages.field_goals_attempted,
                "three_pointers_made": result.averages.three_pointers_made,
                "three_pointers_attempted": result.averages.three_pointers_attempted,
                "free_throws_made": result.averages.free_throws_made,
                "free_throws_attempted": result.averages.free_throws_attempted,
            }
            self._cache.set(cache_key, avgs, SEASON_AVG_TTL)
            logger.info("Season averages cached for player %d (%s)", player_id, season)
            return avgs
        except Exception as exc:
            logger.warning(
                "Could not fetch season averages for player %d: %s", player_id, exc
            )
            return None

    def _analyze_player(
        self,
        player: LivePlayerStatsSchema,
        team_tricode: str,
        season: str,
    ) -> tuple[Optional[LivePlayerAnalysisSchema], Optional[str]]:
        """Returns (analysis, error_reason). Exactly one of them is None."""
        season_avgs = self._get_season_averages(player.player_id, season)
        if season_avgs is None:
            return None, "failed_to_fetch_season_averages"

        avg_minutes = season_avgs["minutes"]
        if avg_minutes <= 0:
            return None, "season_avg_minutes_is_zero"

        ratio = player.minutes / avg_minutes

        expected = LiveExpectedStatsSchema(
            points=rounded(season_avgs["points"] * ratio),
            rebounds=rounded(season_avgs["rebounds"] * ratio),
            assists=rounded(season_avgs["assists"] * ratio),
            field_goals_made=rounded(season_avgs["field_goals_made"] * ratio),
            field_goals_attempted=rounded(season_avgs["field_goals_attempted"] * ratio),
            three_pointers_made=rounded(season_avgs["three_pointers_made"] * ratio),
            three_pointers_attempted=rounded(season_avgs["three_pointers_attempted"] * ratio),
            free_throws_made=rounded(season_avgs["free_throws_made"] * ratio),
            free_throws_attempted=rounded(season_avgs["free_throws_attempted"] * ratio),
        )
        diff = LiveDifferenceSchema(
            points=rounded(player.points - expected.points),
            rebounds=rounded(player.rebounds - expected.rebounds),
            assists=rounded(player.assists - expected.assists),
            field_goals_made=rounded(player.field_goals_made - expected.field_goals_made),
            field_goals_attempted=rounded(
                player.field_goals_attempted - expected.field_goals_attempted
            ),
            three_pointers_made=rounded(
                player.three_pointers_made - expected.three_pointers_made
            ),
            three_pointers_attempted=rounded(
                player.three_pointers_attempted - expected.three_pointers_attempted
            ),
            free_throws_made=rounded(player.free_throws_made - expected.free_throws_made),
            free_throws_attempted=rounded(
                player.free_throws_attempted - expected.free_throws_attempted
            ),
        )

        field_goal_misses_diff = rounded(
            (player.field_goals_attempted - player.field_goals_made)
            - (expected.field_goals_attempted - expected.field_goals_made)
        )
        free_throw_misses_diff = rounded(
            (player.free_throws_attempted - player.free_throws_made)
            - (expected.free_throws_attempted - expected.free_throws_made)
        )
        shooting_impact = calc_shooting_impact(
            diff.field_goals_made,
            diff.field_goals_attempted,
            diff.three_pointers_made,
            diff.free_throws_made,
            field_goal_misses_diff,
            free_throw_misses_diff,
        )
        score = calc_player_score(
            diff.points,
            diff.rebounds,
            diff.assists,
            shooting_impact,
        )
        status = calc_player_status(score)

        analysis = LivePlayerAnalysisSchema(
            player_id=player.player_id,
            name=player.name,
            team=team_tricode,
            minutes=player.minutes,
            current=LiveCurrentStatsSchema(
                points=player.points,
                rebounds=player.rebounds,
                assists=player.assists,
                field_goals_made=player.field_goals_made,
                field_goals_attempted=player.field_goals_attempted,
                three_pointers_made=player.three_pointers_made,
                three_pointers_attempted=player.three_pointers_attempted,
                free_throws_made=player.free_throws_made,
                free_throws_attempted=player.free_throws_attempted,
            ),
            season_average=LiveSeasonAverageSchema(**season_avgs),
            expected_until_now=expected,
            difference=diff,
            shooting_impact=shooting_impact,
            status=status,
            score=score,
        )
        return analysis, None

    def _analyze_boxscore(
        self, boxscore: LiveBoxscoreSchema, season: str
    ) -> tuple[list[LivePlayerAnalysisSchema], list[LiveAnalysisErrorSchema]]:
        """Analyze all players in both teams. Errors are collected, not raised."""
        analyzed: list[LivePlayerAnalysisSchema] = []
        errors: list[LiveAnalysisErrorSchema] = []

        teams = [
            (boxscore.home_team.players, boxscore.home_team.tricode),
            (boxscore.away_team.players, boxscore.away_team.tricode),
        ]
        for players, tricode in teams:
            for player in players:
                result, reason = self._analyze_player(player, tricode, season)
                if result is not None:
                    analyzed.append(result)
                else:
                    errors.append(
                        LiveAnalysisErrorSchema(
                            player_id=player.player_id,
                            name=player.name,
                            reason=reason or "unknown_error",
                        )
                    )

        return analyzed, errors

    # ------------------------------------------------------------------ #
    # Public methods                                                       #
    # ------------------------------------------------------------------ #

    def get_game_analysis(self, game_id: str, season: str) -> LiveGameAnalysisSchema:
        bs = self.live.get_live_boxscore(game_id)
        analyzed, errors = self._analyze_boxscore(bs, season)

        hot = [p for p in analyzed if p.status in ("hot", "above_average")]
        cold = [p for p in analyzed if p.status in ("cold", "below_average")]
        hot.sort(key=lambda p: p.score, reverse=True)
        cold.sort(key=lambda p: p.score)

        return LiveGameAnalysisSchema(
            game_id=game_id,
            season=season,
            game_status=bs.game_status,
            period=bs.period,
            clock=bs.clock,
            analysis_type=ANALYSIS_TYPE,
            players=analyzed,
            hot_players=hot,
            cold_players=cold,
            errors=errors,
        )

    def get_player_live_comparison(
        self, player_id: int, game_id: str, season: str
    ) -> LivePlayerComparisonSchema:
        bs = self.live.get_live_boxscore(game_id)

        # Find player in either team
        player: Optional[LivePlayerStatsSchema] = None
        team_tricode = ""
        for team in (bs.home_team, bs.away_team):
            for p in team.players:
                if p.player_id == player_id:
                    player = p
                    team_tricode = team.tricode
                    break
            if player:
                break

        if player is None:
            raise ValueError(
                f"Jogador {player_id} não encontrado no boxscore do jogo {game_id}. "
                "Verifique se ele já entrou em quadra."
            )

        result, reason = self._analyze_player(player, team_tricode, season)
        if result is None:
            raise ValueError(
                f"Não foi possível analisar player {player_id}: {reason}"
            )

        return LivePlayerComparisonSchema(
            player_id=result.player_id,
            game_id=game_id,
            name=result.name,
            team=result.team,
            minutes=result.minutes,
            current=result.current,
            season_average=result.season_average,
            expected_until_now=result.expected_until_now,
            difference=result.difference,
            shooting_impact=result.shooting_impact,
            status=result.status,
            analysis_type=ANALYSIS_TYPE,
        )

    def get_hot_ranking(
        self, game_id: str, season: str, limit: int
    ) -> HotRankingSchema:
        bs = self.live.get_live_boxscore(game_id)
        analyzed, _ = self._analyze_boxscore(bs, season)

        ranking = sorted(analyzed, key=lambda p: p.score, reverse=True)[:limit]

        return HotRankingSchema(
            game_id=game_id,
            limit=limit,
            ranking=[
                HotRankingPlayerSchema(
                    player_id=p.player_id,
                    name=p.name,
                    team=p.team,
                    minutes=p.minutes,
                    current_points=p.current.points,
                    current_assists=p.current.assists,
                    current_rebounds=p.current.rebounds,
                    expected_points=p.expected_until_now.points,
                    expected_assists=p.expected_until_now.assists,
                    expected_rebounds=p.expected_until_now.rebounds,
                    points_diff=p.difference.points,
                    assists_diff=p.difference.assists,
                    rebounds_diff=p.difference.rebounds,
                    shooting_impact=p.shooting_impact,
                    status=p.status,
                    score=p.score,
                )
                for p in ranking
            ],
        )
