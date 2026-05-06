import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from nba_api.live.nba.endpoints import boxscore, scoreboard

from src.config import USE_FIXTURES
from src.schemas.live_schemas import (
    BlowoutRiskSchema,
    LineupGameSchema,
    LineupPlayerSchema,
    LineupTeamSchema,
    LiveBoxscoreSchema,
    LiveGameSchema,
    LivePlayerStatsSchema,
    LiveTeamBoxscoreSchema,
    LiveTeamSchema,
    PlayerBlowoutImpactSchema,
    TodayGamesSchema,
)
from src.utils.cache import SimpleCache
from src.utils.photos import player_photo_url
from src.utils.stats import (
    calculate_blowout_risk,
    calculate_player_blowout_impact,
    calculate_player_performance_rating,
    rounded,
)
from src.utils.time_utils import format_game_clock, map_game_status, parse_minutes_to_float

logger = logging.getLogger(__name__)

SCOREBOARD_TTL = 30   # seconds
BOXSCORE_TTL = 5      # seconds — clock/score atualizam a cada 5s no front,
                      # então fazia sentido bater no live API com a mesma cadência.
                      # cdn.nba.com aguenta sem stress.

# Fixtures path — relativo à raiz do repo (subindo de src/services).
_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _load_fixture(name: str) -> Optional[dict]:
    """Lê um JSON de tests/fixtures/. Retorna None se não existir."""
    path = _FIXTURES_DIR / name
    if not path.exists():
        logger.warning("Fixture %s não encontrada em %s", name, path)
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _parse_player(p: dict) -> Optional[LivePlayerStatsSchema]:
    """Parser para análise live (filtra quem não jogou)."""
    stats = p.get("statistics", {})
    minutes = parse_minutes_to_float(stats.get("minutes", "PT00M00.00S"))
    if minutes <= 0:
        return None
    return LivePlayerStatsSchema(
        player_id=int(p.get("personId", 0)),
        name=p.get("name", ""),
        position=p.get("position", ""),
        is_starter=str(p.get("starter", "0")) == "1",
        minutes=rounded(minutes),
        points=int(stats.get("points", 0)),
        rebounds=int(stats.get("reboundsTotal", 0)),
        assists=int(stats.get("assists", 0)),
        steals=int(stats.get("steals", 0)),
        blocks=int(stats.get("blocks", 0)),
        turnovers=int(stats.get("turnovers", 0)),
        field_goals_made=int(stats.get("fieldGoalsMade", 0)),
        field_goals_attempted=int(stats.get("fieldGoalsAttempted", 0)),
        three_pointers_made=int(stats.get("threePointersMade", 0)),
        three_pointers_attempted=int(stats.get("threePointersAttempted", 0)),
        free_throws_made=int(stats.get("freeThrowsMade", 0)),
        free_throws_attempted=int(stats.get("freeThrowsAttempted", 0)),
        plus_minus=int(stats.get("plusMinusPoints", 0)),
        fouls=int(stats.get("foulsPersonal", 0)),
        # 'oncourt' vem como string "1"/"0" (às vezes "0" mesmo entre jogadas).
        # Default True quando o campo está ausente — evita marcar metade do
        # boxscore como "no banco" se a NBA mudar o nome do campo.
        on_court=str(p.get("oncourt", "1")) == "1",
    )


def _parse_lineup_player(
    p: dict,
    game_blowout_pct: int = 0,
    game_blowout_level: str = "low",
) -> LineupPlayerSchema:
    """
    Parser para a aba Lineups.

    Diferenças em relação a `_parse_player`:
    - NÃO filtra por minutes <= 0 (precisa mostrar reservas que não entraram)
    - Inclui campos oficiais: starter, played, status, notPlayingReason, jerseyNum
    - Calcula performance_rating + photo_url
    - Calcula blowout_impact por jogador (None se não fizer sentido pra ele)

    Args:
        p: dict cru do boxscore
        game_blowout_pct: 0–100 do jogo (já calculado em get_lineup)
        game_blowout_level: 'low'|'medium'|'high'|'final'
    """
    stats = p.get("statistics", {})
    minutes = parse_minutes_to_float(stats.get("minutes", "PT00M00.00S"))
    person_id = int(p.get("personId", 0))

    points    = int(stats.get("points", 0))
    rebounds  = int(stats.get("reboundsTotal", 0))
    assists   = int(stats.get("assists", 0))
    steals    = int(stats.get("steals", 0))
    blocks    = int(stats.get("blocks", 0))
    turnovers = int(stats.get("turnovers", 0))
    fouls     = int(stats.get("foulsPersonal", 0))
    plus_minus = int(stats.get("plusMinusPoints", 0))
    fgm = int(stats.get("fieldGoalsMade", 0))
    fga = int(stats.get("fieldGoalsAttempted", 0))
    tpm = int(stats.get("threePointersMade", 0))
    tpa = int(stats.get("threePointersAttempted", 0))
    ftm = int(stats.get("freeThrowsMade", 0))
    fta = int(stats.get("freeThrowsAttempted", 0))

    rating, label, low_conf = calculate_player_performance_rating(
        points=points,
        rebounds=rebounds,
        assists=assists,
        steals=steals,
        blocks=blocks,
        turnovers=turnovers,
        fouls=fouls,
        plus_minus=plus_minus,
        minutes=minutes,
        field_goals_made=fgm,
        field_goals_attempted=fga,
        three_pointers_made=tpm,
        free_throws_made=ftm,
        free_throws_attempted=fta,
    )

    is_starter_flag = str(p.get("starter", "0")) == "1"
    impact_dict = calculate_player_blowout_impact(
        player_minutes=minutes,
        is_starter=is_starter_flag,
        game_blowout_pct=game_blowout_pct,
        game_blowout_level=game_blowout_level,
    )
    blowout_impact_payload = (
        PlayerBlowoutImpactSchema(**impact_dict) if impact_dict else None
    )

    return LineupPlayerSchema(
        player_id=person_id,
        name=p.get("name", ""),
        jersey_num=str(p.get("jerseyNum", "")),
        position=p.get("position", "") or "",
        is_starter=is_starter_flag,
        is_on_court=str(p.get("oncourt", "0")) == "1",
        played=str(p.get("played", "0")) == "1",
        status=str(p.get("status", "ACTIVE")),
        not_playing_reason=p.get("notPlayingReason"),
        photo_url=player_photo_url(person_id),
        minutes=rounded(minutes),
        points=points,
        rebounds=rebounds,
        assists=assists,
        steals=steals,
        blocks=blocks,
        turnovers=turnovers,
        fouls=fouls,
        field_goals_made=fgm,
        field_goals_attempted=fga,
        three_pointers_made=tpm,
        three_pointers_attempted=tpa,
        free_throws_made=ftm,
        free_throws_attempted=fta,
        plus_minus=plus_minus,
        performance_rating=rating,
        performance_label=label,
        low_confidence=low_conf,
        blowout_impact=blowout_impact_payload,
    )


def _parse_lineup_team(
    team: dict,
    game_blowout_pct: int = 0,
    game_blowout_level: str = "low",
) -> LineupTeamSchema:
    """Separa jogadores em starters, bench e inactive."""
    raw_players = team.get("players", [])
    parsed = [
        _parse_lineup_player(p, game_blowout_pct, game_blowout_level)
        for p in raw_players
    ]

    starters: list[LineupPlayerSchema] = []
    bench:    list[LineupPlayerSchema] = []
    inactive: list[LineupPlayerSchema] = []

    for p in parsed:
        if p.status != "ACTIVE":
            inactive.append(p)
        elif p.is_starter:
            starters.append(p)
        else:
            bench.append(p)

    # Ordenação: starters mantêm ordem da NBA (1..5);
    # bench ordena por minutos jogados (quem mais joga primeiro);
    # inactive por nome.
    bench.sort(key=lambda x: (-x.minutes, x.name))
    inactive.sort(key=lambda x: x.name)

    if len(starters) != 5:
        logger.warning(
            "Time %s tem %d titulares (esperado 5) — boxscore pode estar atrasado",
            team.get("teamTricode", "?"), len(starters),
        )

    city = team.get("teamCity", "")
    name = team.get("teamName", "")
    return LineupTeamSchema(
        team_id=int(team.get("teamId", 0)),
        name=f"{city} {name}".strip(),
        tricode=team.get("teamTricode", ""),
        score=int(team.get("score", 0)),
        starters=starters,
        bench=bench,
        inactive=inactive,
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

    def fetch_scoreboard(self) -> TodayGamesSchema:
        """
        Fetch live scoreboard directly from the NBA API.
        Called by the background worker — no caching here.

        Quando USE_FIXTURES=1, lê de tests/fixtures/scoreboard_today.json
        em vez de bater na NBA. Útil pra dev offline / dia sem jogos.
        """
        if USE_FIXTURES:
            logger.info("USE_FIXTURES: lendo scoreboard de fixture")
            fixture = _load_fixture("scoreboard_today.json")
            if fixture is not None:
                data = fixture["scoreboard"]
            else:
                raise RuntimeError("Fixture scoreboard_today.json não encontrada")
        else:
            logger.info("Fetching live scoreboard from NBA API.")
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
                    # gameTimeUTC vem como "2026-05-04T23:00:00Z" no scoreboard
                    # da NBA Live API. Mantemos como string crua — o front
                    # formata pro timezone do usuário com Intl.DateTimeFormat.
                    game_time_utc=g.get("gameTimeUTC") or None,
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
        logger.info("Scoreboard fetched: %d games.", len(games))
        return result

    def get_today_games(self) -> TodayGamesSchema:
        """Legacy method kept for internal use (live analysis, boxscore routes)."""
        cached = self._cache.get("scoreboard")
        if cached:
            logger.debug("Scoreboard served from cache")
            return cached
        result = self.fetch_scoreboard()
        self._cache.set("scoreboard", result, SCOREBOARD_TTL)
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

    def _fetch_raw_game_data(self, game_id: str) -> dict:
        """
        Cache compartilhado do JSON cru do boxscore (TTL curto).
        get_live_boxscore e get_lineup consomem o mesmo dado, evitando
        2 requests à NBA Live API a cada poll.

        Em modo USE_FIXTURES: tenta `boxscore_<game_id>.json`, depois cai
        no `boxscore_blowout_final.json` como fallback. Permite testar
        com jogo de blowout decidido (Celtics x Mavs G5) quando não há
        jogo ao vivo.
        """
        cache_key = f"raw_boxscore:{game_id}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        if USE_FIXTURES:
            fixture = (
                _load_fixture(f"boxscore_{game_id}.json")
                or _load_fixture("boxscore_blowout_final.json")
            )
            if fixture is None:
                raise RuntimeError("Nenhuma fixture de boxscore encontrada")
            game_data = fixture["game"]
        else:
            try:
                bs = boxscore.BoxScore(game_id=game_id)
                game_data = bs.get_dict()["game"]
            except Exception as exc:
                raise RuntimeError(f"Erro ao buscar boxscore para {game_id}: {exc}") from exc

        self._cache.set(cache_key, game_data, BOXSCORE_TTL)
        return game_data

    def get_lineup(self, game_id: str) -> LineupGameSchema:
        """
        Lineups completas (titulares + reservas + inativos) com foto e
        nota de desempenho. Tudo direto da NBA Live API — sem inferência.
        """
        cache_key = f"lineup:{game_id}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.debug("Lineup %s served from cache", game_id)
            return cached

        logger.info("Building lineup for game %s", game_id)
        game_data = self._fetch_raw_game_data(game_id)

        game_status = map_game_status(game_data.get("gameStatus", 0))
        period = int(game_data.get("period", 0))
        clock = format_game_clock(game_data.get("gameClock", ""))

        # Calcula blowout do JOGO primeiro (precisa só dos placares).
        # Os parsers de team/player recebem esse contexto pra decidir
        # individualmente quem deveria ganhar a flag de "Risco de descanso".
        home_score = int(game_data.get("homeTeam", {}).get("score", 0))
        away_score = int(game_data.get("awayTeam", {}).get("score", 0))
        is_playoff = len(game_id) >= 4 and game_id[2:4] == "04"
        bo_pct, bo_level, bo_reason = calculate_blowout_risk(
            period=period,
            clock=clock,
            home_score=home_score,
            away_score=away_score,
            game_status=game_status,
            is_playoff=is_playoff,
        )

        home = _parse_lineup_team(game_data.get("homeTeam", {}), bo_pct, bo_level)
        away = _parse_lineup_team(game_data.get("awayTeam", {}), bo_pct, bo_level)

        result = LineupGameSchema(
            game_id=game_id,
            game_status=game_status,
            period=period,
            clock=clock,
            home_team=home,
            away_team=away,
            blowout_risk=BlowoutRiskSchema(
                percentage=bo_pct, level=bo_level, reason=bo_reason
            ),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._cache.set(cache_key, result, BOXSCORE_TTL)
        return result
