import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from datetime import datetime, timezone

from src.schemas.live_schemas import (
    BlowoutRiskSchema,
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
    PaceProjectionSchema,
)
from src.services.live_game_service import LiveGameService
from src.services.player_analysis_service import PlayerAnalysisService
from src.utils.cache import PersistentCache
from src.utils.stats import (
    calc_player_score,
    calc_player_status,
    calc_shooting_impact,
    rounded,
)

logger = logging.getLogger(__name__)

SEASON_AVG_TTL = 86_400    # 24 hours — médias mudam no máximo 1x/dia
ANALYSIS_TYPE = "experimental_live_analysis"


class LiveAnalysisService:
    def __init__(
        self,
        live_game_service: LiveGameService,
        player_analysis_service: PlayerAnalysisService,
    ) -> None:
        self.live = live_game_service
        self.player_analysis = player_analysis_service
        self._cache = PersistentCache()

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
            result = self.player_analysis.get_season_analysis(player_id, season, fast=True)
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
            fouls=player.fouls,
            on_court=player.on_court,
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
        """
        Analisa todos os jogadores dos dois times em paralelo.

        ThreadPoolExecutor dispara todas as buscas de médias simultaneamente,
        então o tempo total é ~6 s (1 timeout) e não 20×6 s = 120 s.
        """
        tasks = [
            (player, team.tricode)
            for team in (boxscore.home_team, boxscore.away_team)
            for player in team.players
        ]

        analyzed: list[LivePlayerAnalysisSchema] = []
        errors:   list[LiveAnalysisErrorSchema]  = []

        with ThreadPoolExecutor(max_workers=min(len(tasks), 16)) as pool:
            future_map = {
                pool.submit(self._analyze_player, player, tricode, season): player
                for player, tricode in tasks
            }
            for future in as_completed(future_map):
                player = future_map[future]
                try:
                    result, reason = future.result()
                except Exception as exc:
                    logger.error("Erro inesperado analisando jogador %d: %s", player.player_id, exc)
                    result, reason = None, f"unexpected_error: {exc}"

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

    @staticmethod
    def _project_game(stat: float, minutes: float, avg_stat: float, avg_minutes: float) -> float:
        """
        Projeção BASE (blended) para um jogo típico (avg_minutes).

        Mistura o ritmo atual deste jogo com o ritmo histórico da temporada.
        Conforme o jogador acumula minutos, o peso do ritmo atual cresce
        (até 60%), mas a temporada nunca some — isso evita que um chute
        quente de 5 minutos vire previsão absurda.

        Responde: "considerando o que ele costuma fazer + como está hoje,
        quanto deve terminar?"
        """
        if avg_minutes <= 0:
            return round(avg_stat, 1)
        if minutes < 1.0:
            return round(avg_stat, 1)
        current_ppm = stat / minutes
        season_ppm  = avg_stat / avg_minutes
        alpha = min(minutes / avg_minutes, 0.60)
        return round((alpha * current_ppm + (1.0 - alpha) * season_ppm) * avg_minutes, 1)

    @staticmethod
    def _is_playoff_game(game_id: str) -> bool:
        """
        NBA game IDs seguem padrão '00<TT><Y><NNNNN>' onde TT identifica o tipo:
            01 = Preseason   02 = Regular Season
            03 = All-Star    04 = Playoffs
            05 = Play-in
        Em playoffs, blowout praticamente não rola — técnicos mantêm titulares
        mesmo com grande vantagem (medo de virada, fechamento de série, etc.).
        """
        if not game_id or len(game_id) < 4:
            return False
        return game_id[2:4] == "04"

    @staticmethod
    def _compute_game_context(
        period: int,
        clock: str,
        home_score: int,
        away_score: int,
        consider_blowout: bool = True,
    ) -> dict:
        """
        Calcula contexto do jogo usado pra ajustar a projeção.

        Retorna:
        - period (int)            — período atual (1..4 OT=5+)
        - score_diff (int)        — diferença absoluta de placar
        - minutes_elapsed (float) — minutos decorridos no jogo (clamp >=0.1)
        - blowout_severity (float in [0,1]) — quão provável é o garbage time:
            * 0.0 → jogo normal/disputado
            * 0.5 → Q4 com 10+ pts de diferença (estrela pode sair antes)
            * 0.7 → Q3+ com 20+ (técnico já considerando descansar titulares)
            * 1.0 → Q4 com 15+ (banco assumindo, estrelas saem)
        """
        try:
            if ":" in clock:
                mm, ss = clock.split(":")
                clock_minutes_remaining = int(mm) + int(ss) / 60.0
            else:
                clock_minutes_remaining = 12.0
        except (ValueError, AttributeError):
            clock_minutes_remaining = 12.0

        period_clamped = max(period, 1)
        minutes_elapsed = (period_clamped - 1) * 12 + (12 - clock_minutes_remaining)
        minutes_elapsed = max(minutes_elapsed, 0.1)
        score_diff = abs(home_score - away_score)

        # Blowout: thresholds calibrados pra padrão NBA. Q3 com 20+ já
        # sinaliza intenção de descanso; Q4 com 15+ é praticamente garantido.
        # Em jogos sem blowout (playoffs, decisão de série, etc.) o usuário
        # desativa via flag — todos os jogadores ficam sem ajuste de garbage.
        blowout_severity = 0.0
        if consider_blowout:
            if period_clamped >= 4 and score_diff >= 15:
                blowout_severity = 1.0
            elif period_clamped >= 3 and score_diff >= 20:
                blowout_severity = 0.7
            elif period_clamped >= 4 and score_diff >= 10:
                blowout_severity = 0.5

        # Pace: ritmo do jogo vs média NBA (~220 pts totais).
        # Shootout (240+) = ritmo continua quente; jogo lento (200-) = cai.
        # Em Q1 cedo o sample é ruim demais — peso menor pra evitar overreact.
        # Clamp em [0.92, 1.08]: ajuste sutil, não mexe muito na projeção.
        total_pts = home_score + away_score
        if minutes_elapsed >= 6.0:  # precisa pelo menos meio quarto pra dar significado
            projected_total = (total_pts / minutes_elapsed) * 48.0
            raw_factor = projected_total / 220.0
            # Confiança cresce com tempo de jogo: peso vai de 0.5 (6 min) a 1.0 (24+ min)
            pace_confidence = min((minutes_elapsed - 6.0) / 18.0 + 0.5, 1.0)
            # Ajuste suavizado pela confiança
            pace_factor = 1.0 + (raw_factor - 1.0) * pace_confidence
            pace_factor = max(0.92, min(pace_factor, 1.08))
        else:
            pace_factor = 1.0

        # Minutos restantes reais do jogo (considera OT: cada prorrogação = 5 min).
        total_game_minutes = 48.0 if period_clamped <= 4 else 48.0 + (period_clamped - 4) * 5.0
        game_minutes_remaining = max(total_game_minutes - minutes_elapsed, 0.0)

        return {
            "period": period_clamped,
            "score_diff": score_diff,
            "minutes_elapsed": minutes_elapsed,
            "blowout_severity": blowout_severity,
            "pace_factor": pace_factor,
            "game_minutes_remaining": game_minutes_remaining,
        }

    @staticmethod
    def _project_to_end(
        stat: int,
        minutes: float,
        avg_stat: float,
        avg_minutes: float,
        fouls: int = 0,
        period: int = 1,
        blowout_severity: float = 0.0,
        pace_factor: float = 1.0,
        game_minutes_remaining: float = 0.0,
        is_final: bool = False,
    ) -> tuple[float, float, float]:
        """
        Projeção até o FIM DO JOGO com margem de erro (low, expected, high).

        Mistura ritmo atual (peso ALTO) com ritmo da temporada (peso baixo,
        ~10-25%) só pra estabilizar quando a amostra ainda é pequena.

        Lógica:
        - Calcula ritmo atual (stat por minuto deste jogo)
        - Calcula ritmo da temporada (stat por minuto histórico)
        - Mistura com peso da temporada decrescente: 25% no início → 10%
          após ~10 minutos jogados
        - Estima minutos restantes que ele vai jogar (avg_minutes - minutes,
          clamp em 0). avg_minutes já incorpora os descansos típicos dele.
        - Projeta total final = atual + ritmo_misto × restantes
        - Adiciona margem de erro ±, decrescente conforme o jogo avança:
          15% no início → 5% perto do fim do jogo

        Edge cases:
        - minutes <= 0 → retorna (0, 0, 0)
        - avg_minutes <= 0 → fallback 32 min (média típica NBA)
        - Já jogou mais que avg_minutes → projeta como atual (sem extrapolar)

        Returns: (low, expected, high) já arredondados para 1 casa.
        """
        # ── Jogo finalizado: zero extrapolação ────────────────────────────
        # Bug histórico (caso Barnes): jogador com 4 reb em 6 minutos
        # ganhava projeção de ~10 reb mesmo após o apito final, porque a
        # função extrapolava avg_minutes × ritmo. Quando o jogo acabou,
        # o stat real É a final — sem margem, sem incerteza.
        if is_final:
            base = float(stat)
            return (base, base, base)

        if minutes <= 0:
            return (0.0, 0.0, 0.0)

        base_avg_minutes = avg_minutes if avg_minutes > 0 else 32.0
        target_minutes = base_avg_minutes

        # ── 1. Ajuste de target_minutes pelo tempo real do jogo ──────────
        # O avg_minutes reflete jogos onde o jogador saiu cedo (blowout,
        # descanso, lesão). Se o jogo ainda tem tempo, ele provavelmente
        # vai jogar mais do que a média sugere.
        # Usamos a fração típica de tempo em quadra (avg/48) pra estimar
        # quantos minutos adicionais ele ainda vai jogar.
        if game_minutes_remaining > 0:
            on_court_fraction = base_avg_minutes / 48.0
            expected_remaining_by_game = game_minutes_remaining * on_court_fraction
            # target = max(média, o que ele já jogou + o que o jogo ainda permite)
            target_minutes = max(target_minutes, minutes + expected_remaining_by_game)

        # ── 2. Redutores de contexto (aplicados após extensão) ───────────

        # Blowout: corta até 20% dos minutos esperados quando vai pro garbage.
        if blowout_severity > 0:
            target_minutes *= (1.0 - 0.20 * blowout_severity)

        # Foul trouble: 5+ faltas = alto risco de banco/foul out;
        # 4 em <=Q3 = técnico costuma proteger o jogador.
        foul_rate_factor = 1.0
        if fouls >= 5:
            target_minutes *= 0.85
            foul_rate_factor = 0.90  # joga mais defensivo, menos agressivo
        elif fouls >= 4 and period <= 3:
            target_minutes *= 0.92
            foul_rate_factor = 0.95

        # Já jogou mais que o target — encerra sem extrapolar.
        if minutes >= target_minutes:
            base = float(stat)
            margin = base * 0.05
            return (round(base - margin, 1), round(base, 1), round(base + margin, 1))

        current_rate = stat / minutes
        season_rate = avg_stat / base_avg_minutes if avg_stat > 0 else current_rate

        # ── 3. Peso da temporada ─────────────────────────────────────────
        # Base: 25% no início → 10% após 10 min jogados.
        # Extra: reduz ainda mais quando o jogador está claramente acima da
        # média — se ele está 2× o ritmo histórico, a temporada explica menos
        # o que está acontecendo hoje.
        sample_factor = min(minutes / 10.0, 1.0)
        season_weight = 0.25 - (0.15 * sample_factor)          # 0.10 – 0.25
        if season_rate > 0 and current_rate > season_rate:
            hot_ratio = current_rate / season_rate              # ex: 2.4 = 2.4× a média
            # A cada 0.5× acima da média, reduz 20% do season_weight restante
            # hot_ratio=1.5 → -20%;  hot_ratio=2.0 → -40%;  hot_ratio=3+ → -80%
            hot_discount = min((hot_ratio - 1.0) * 0.40, 0.80)
            season_weight *= (1.0 - hot_discount)

        blended_rate = (1.0 - season_weight) * current_rate + season_weight * season_rate

        # Foul trouble e pace ajustam o ritmo.
        blended_rate *= foul_rate_factor
        blended_rate *= pace_factor

        remaining = max(target_minutes - minutes, 0.0)
        expected = stat + blended_rate * remaining

        # ── 3.5 Cap de sanidade ──────────────────────────────────────────
        # Mesmo um jogador "explodindo" não pode projetar 4× a média histórica.
        # Limita o teto absoluto a max(avg × 2.5, avg + 6) — permite upside
        # generoso mas evita projeção absurda quando avg é baixo (ex: cara
        # de 5 reb/jogo não projeta 20 reb por causa de 6 min quentes).
        if avg_stat > 0:
            sanity_cap = max(avg_stat * 2.5, avg_stat + 6.0)
            # O cap não pode ficar abaixo do que o jogador JÁ tem.
            sanity_cap = max(sanity_cap, float(stat))
            expected = min(expected, sanity_cap)

        # ── 4. Margem de incerteza ───────────────────────────────────────
        progress = minutes / max(target_minutes, 1.0)
        uncertainty = max(0.15 * (1.0 - progress), 0.05)

        # Foul trouble ou blowout → mais incerteza nos minutos restantes.
        if fouls >= 4 or blowout_severity > 0.4:
            uncertainty = min(uncertainty + 0.05, 0.20)

        margin = expected * uncertainty

        # Low não pode ficar abaixo do que ele já tem — não dá pra "desfazer" stats.
        low = max(float(stat), expected - margin)
        high = expected + margin

        return (round(low, 1), round(expected, 1), round(high, 1))

    def get_hot_ranking(
        self,
        game_id: str,
        season: str,
        limit: int,
        consider_blowout: Optional[bool] = None,
    ) -> HotRankingSchema:
        """
        consider_blowout:
          - None (padrão): auto-detecta. Playoffs = False, resto = True.
          - True/False: override explícito do usuário (UI manda quando o
            usuário liga/desliga o toggle de blowout).
        """
        bs = self.live.get_live_boxscore(game_id)
        analyzed, _ = self._analyze_boxscore(bs, season)

        ranking = sorted(analyzed, key=lambda p: p.score, reverse=True)[:limit]

        # Auto-detecção: jogos de playoff ignoram blowout por padrão.
        if consider_blowout is None:
            consider_blowout = not self._is_playoff_game(game_id)

        is_final = bs.game_status == "final"
        is_playoff = self._is_playoff_game(game_id)

        # Contexto do jogo é o mesmo pra todos os jogadores deste game.
        ctx = self._compute_game_context(
            bs.period, bs.clock,
            bs.home_team.score, bs.away_team.score,
            consider_blowout=consider_blowout,
        )
        blowout_risk_legacy = ctx["blowout_severity"] > 0.0  # flag antiga por jogador

        # Risco de blowout (porcentagem qualitativa) — exposto no payload.
        from src.utils.stats import calculate_blowout_risk
        bo_pct, bo_level, bo_reason = calculate_blowout_risk(
            period=bs.period,
            clock=bs.clock,
            home_score=bs.home_team.score,
            away_score=bs.away_team.score,
            game_status=bs.game_status,
            is_playoff=is_playoff,
        )
        blowout_payload = BlowoutRiskSchema(
            percentage=bo_pct, level=bo_level, reason=bo_reason
        )

        def _proj(stat: int, minutes: float, avg_stat: float, avg_minutes: float, fouls: int):
            """Wrapper que aplica fouls + contexto do jogo na projeção."""
            return PaceProjectionSchema(
                **dict(zip(
                    ("low", "expected", "high"),
                    self._project_to_end(
                        stat, minutes, avg_stat, avg_minutes,
                        fouls=fouls,
                        period=ctx["period"],
                        blowout_severity=ctx["blowout_severity"],
                        pace_factor=ctx["pace_factor"],
                        game_minutes_remaining=ctx["game_minutes_remaining"],
                        is_final=is_final,
                    ),
                ))
            )

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
                    projected_points=self._project_game(
                        p.current.points, p.minutes,
                        p.season_average.points, p.season_average.minutes,
                    ),
                    projected_assists=self._project_game(
                        p.current.assists, p.minutes,
                        p.season_average.assists, p.season_average.minutes,
                    ),
                    projected_rebounds=self._project_game(
                        p.current.rebounds, p.minutes,
                        p.season_average.rebounds, p.season_average.minutes,
                    ),
                    pace_projection_points=_proj(
                        p.current.points, p.minutes,
                        p.season_average.points, p.season_average.minutes, p.fouls,
                    ),
                    pace_projection_assists=_proj(
                        p.current.assists, p.minutes,
                        p.season_average.assists, p.season_average.minutes, p.fouls,
                    ),
                    pace_projection_rebounds=_proj(
                        p.current.rebounds, p.minutes,
                        p.season_average.rebounds, p.season_average.minutes, p.fouls,
                    ),
                    fouls=p.fouls,
                    foul_trouble=p.fouls >= 4,
                    blowout_risk=blowout_risk_legacy,
                    on_court=p.on_court,
                    shooting_impact=p.shooting_impact,
                    status=p.status,
                    score=p.score,
                )
                for p in ranking
            ],
            game_status=bs.game_status,
            period=bs.period,
            clock=bs.clock,
            home_score=bs.home_team.score,
            away_score=bs.away_team.score,
            blowout_risk=blowout_payload,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
