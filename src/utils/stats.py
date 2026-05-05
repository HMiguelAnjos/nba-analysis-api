from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.schemas.nba_schemas import GameLogSchema

TREND_THRESHOLD = 1.0
POINTS_WEIGHT = 0.85
REBOUNDS_WEIGHT = 0.6
ASSISTS_WEIGHT = 0.7
SHOT_VOLUME_BONUS_WEIGHT = 0.12
FIELD_GOAL_MADE_WEIGHT = 0.45
THREE_POINTER_MADE_WEIGHT = 0.35
FREE_THROW_MADE_WEIGHT = 0.2
FIELD_GOAL_MISS_WEIGHT = 0.3
FREE_THROW_MISS_WEIGHT = 0.15


def parse_minutes(min_str: str) -> float:
    """Convert MIN field to float minutes. Handles '34:30', '34.5', '34'."""
    s = str(min_str).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            return int(parts[0]) + int(parts[1]) / 60
        except (ValueError, IndexError):
            return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def rounded(value: float) -> float:
    return round(value, 1)


def safe_average(values: list[float]) -> float:
    if not values:
        return 0.0
    return rounded(sum(values) / len(values))


def calc_stat_averages(logs: list["GameLogSchema"]) -> dict[str, float]:
    if not logs:
        return {
            "points": 0.0,
            "rebounds": 0.0,
            "assists": 0.0,
            "minutes": 0.0,
            "field_goals_made": 0.0,
            "field_goals_attempted": 0.0,
            "three_pointers_made": 0.0,
            "three_pointers_attempted": 0.0,
            "free_throws_made": 0.0,
            "free_throws_attempted": 0.0,
        }
    return {
        "points": safe_average([float(g.points) for g in logs]),
        "rebounds": safe_average([float(g.rebounds) for g in logs]),
        "assists": safe_average([float(g.assists) for g in logs]),
        "minutes": safe_average([parse_minutes(g.minutes) for g in logs]),
        "field_goals_made": safe_average([float(g.field_goals_made) for g in logs]),
        "field_goals_attempted": safe_average([float(g.field_goals_attempted) for g in logs]),
        "three_pointers_made": safe_average([float(g.three_pointers_made) for g in logs]),
        "three_pointers_attempted": safe_average([float(g.three_pointers_attempted) for g in logs]),
        "free_throws_made": safe_average([float(g.free_throws_made) for g in logs]),
        "free_throws_attempted": safe_average([float(g.free_throws_attempted) for g in logs]),
    }


def calc_trend_status(last5_pts: float, season_pts: float) -> str:
    diff = last5_pts - season_pts
    if diff > TREND_THRESHOLD:
        return "above_average"
    if diff < -TREND_THRESHOLD:
        return "below_average"
    return "stable"


def calc_shooting_impact(
    field_goals_made_diff: float,
    field_goals_attempted_diff: float,
    three_pointers_made_diff: float,
    free_throws_made_diff: float,
    field_goal_misses_diff: float,
    free_throw_misses_diff: float,
) -> float:
    return rounded(
        field_goals_made_diff * FIELD_GOAL_MADE_WEIGHT
        + max(field_goals_attempted_diff, 0.0) * SHOT_VOLUME_BONUS_WEIGHT
        + three_pointers_made_diff * THREE_POINTER_MADE_WEIGHT
        + free_throws_made_diff * FREE_THROW_MADE_WEIGHT
        - field_goal_misses_diff * FIELD_GOAL_MISS_WEIGHT
        - free_throw_misses_diff * FREE_THROW_MISS_WEIGHT
    )


def calc_player_score(
    points_diff: float,
    rebounds_diff: float,
    assists_diff: float,
    shooting_impact: float,
) -> float:
    box_score_component = (
        points_diff * POINTS_WEIGHT
        + rebounds_diff * REBOUNDS_WEIGHT
        + assists_diff * ASSISTS_WEIGHT
    )
    return rounded(box_score_component + shooting_impact)


def calc_player_status(score: float) -> str:
    if score >= 5:
        return "hot"
    if score >= 2:
        return "above_average"
    if score > -2:
        return "normal"
    if score > -5:
        return "below_average"
    return "cold"


# ---------------------------------------------------------------------------
# Performance rating (0–10) para a aba Lineups
# ---------------------------------------------------------------------------
# Métrica explicável pra dar uma nota rápida do jogador no jogo atual.
# Não é PER nem Game Score — é uma combinação ponderada simples calibrada
# pra escala 0–10 onde:
#   ~5.0 → jogador médio jogando os minutos típicos
#   ~7.0 → desempenho sólido, acima da média
#   ~8.5 → desempenho de destaque, candidato a Player of the Game
#   <5.0 → abaixo do esperado / jogou pouco / muitos erros
#
# Pesos derivados de valores médios da NBA (ex: 1 roubo "vale mais" que
# 1 ponto porque é mais raro e tem alto impacto). Ajustar com base em
# feedback prático.

# Pesos por stat — multiplicados pelo valor bruto.
_RATING_WEIGHTS = {
    "points":    0.50,
    "rebounds":  0.70,
    "assists":   0.90,
    "steals":    1.80,
    "blocks":    1.80,
    "turnovers": -1.20,
    "fouls":     -0.30,
    "plus_minus": 0.10,
}

# Bônus de eficiência: cada 10 pontos percentuais de eFG acima de 50%
# vira +0.5 ponto. Cada 10pp abaixo, -0.5.
_EFG_NEUTRAL = 0.50
_EFG_WEIGHT = 5.0

# Limiar de minutos abaixo do qual a confiança é baixa.
LOW_CONFIDENCE_MINUTES = 10.0
# Quando confiança é baixa, a nota fica capped — não dá pra dar 9.0
# pra cara que jogou 4 minutos.
LOW_CONFIDENCE_CAP = 7.0


# ---------------------------------------------------------------------------
# Blowout risk (probabilidade de garbage time)
# ---------------------------------------------------------------------------
# Combina diferença de placar, período, tempo restante e tipo de jogo
# (playoff = quase nunca tem blowout) numa porcentagem 0–100 com nível
# qualitativo e explicação curta.

def _parse_clock_minutes_remaining(clock: str) -> float:
    """'06:24' → 6.4 minutos. Sem clock → 12 (período inteiro)."""
    s = (clock or "").strip()
    if ":" not in s:
        return 12.0
    try:
        mm, ss = s.split(":")
        return int(mm) + int(ss) / 60.0
    except (ValueError, IndexError):
        return 12.0


def calculate_blowout_risk(
    period: int,
    clock: str,
    home_score: int,
    away_score: int,
    game_status: str = "in_progress",
    is_playoff: bool = False,
) -> tuple[int, str, str]:
    """
    Estima o risco de garbage time (titulares saindo).

    Returns:
        (percentage 0-100, level, reason)
        level ∈ {"low", "medium", "high", "final"}.

    Regras (calibradas pra padrão NBA):
    - Jogo finalizado → 0%, level "final".
    - Não iniciado → 0%, level "low".
    - Q1: praticamente nunca tem blowout (cap 10%).
    - Q2: começa a importar com diff > 18.
    - Q3: risco médio/alto se diff > 20.
    - Q4: risco alto se diff > 15 com pouco tempo restante.
    - Playoffs: corte de 60% no risco (técnicos mantêm titulares).
    """
    if game_status == "final":
        return (0, "final", "Jogo encerrado")
    if game_status == "not_started":
        return (0, "low", "Jogo ainda não começou")

    score_diff = abs(home_score - away_score)
    period_clamped = max(period, 1)
    clock_remaining = _parse_clock_minutes_remaining(clock)
    period_label = f"Q{period_clamped}" if period_clamped <= 4 else f"OT{period_clamped - 4}"

    # ── Componente 1: diferença de placar (escala não-linear) ───────────────
    # Diff de 10 ainda é virável; 20 é difícil; 30 é praticamente sentenciado.
    if score_diff <= 5:
        diff_score = 0.0
    elif score_diff <= 10:
        diff_score = (score_diff - 5) * 4.0          # 0→20
    elif score_diff <= 20:
        diff_score = 20.0 + (score_diff - 10) * 4.0  # 20→60
    elif score_diff <= 30:
        diff_score = 60.0 + (score_diff - 20) * 3.0  # 60→90
    else:
        diff_score = 90.0 + min(score_diff - 30, 10) * 1.0  # cap 100

    # ── Componente 2: período (mais tarde = mais peso pro diff) ─────────────
    # Q1 segura muito — qualquer diff é cedo demais pra concluir blowout.
    period_multiplier = {1: 0.20, 2: 0.45, 3: 0.75, 4: 1.0}.get(period_clamped, 0.50)

    # ── Componente 3: tempo restante no quarto atual ────────────────────────
    # Em Q4 com pouco tempo, mesmo diff de 12 é praticamente blowout.
    # Pesos calibrados pra "Q4 + 18 pts + 3min restantes" ≈ 70%.
    if period_clamped >= 4:
        # Q4 com <6 min restantes ganha boost proporcional ao tempo gasto.
        time_pressure = max((6.0 - clock_remaining) / 6.0, 0.0)
    else:
        time_pressure = 0.0

    base = diff_score * period_multiplier + time_pressure * 25.0

    # ── Playoffs: técnicos não relaxam ──────────────────────────────────────
    if is_playoff:
        base *= 0.4

    percentage = int(max(0, min(100, round(base))))

    # ── Nível qualitativo ───────────────────────────────────────────────────
    # 60+ = "high": acima disso é difícil reverter na NBA
    # 30+ = "medium": titulares já podem começar a sair
    if percentage >= 60:
        level = "high"
    elif percentage >= 30:
        level = "medium"
    else:
        level = "low"

    # ── Explicação humana ───────────────────────────────────────────────────
    if percentage <= 5:
        reason = f"Jogo equilibrado ({score_diff} pts no {period_label})"
    elif period_clamped == 1:
        reason = f"Diferença de {score_diff} pts no Q1 — cedo pra concluir"
    elif period_clamped >= 4 and clock_remaining < 4 and score_diff >= 12:
        reason = f"Diferença de {score_diff} pts no {period_label} com {clock_remaining:.0f} min restantes"
    elif percentage >= 65:
        reason = f"Diferença de {score_diff} pts no {period_label} — garbage time iminente"
    elif percentage >= 35:
        reason = f"Diferença de {score_diff} pts no {period_label} — banco pode entrar antes"
    else:
        reason = f"Diferença de {score_diff} pts no {period_label}"

    return (percentage, level, reason)


def _effective_field_goal_pct(
    fgm: int, fga: int, three_pm: int
) -> float | None:
    """
    eFG% = (FGM + 0.5 × 3PM) / FGA.

    Retorna None se não tentou nenhum arremesso (não dá pra avaliar tiro).
    """
    if fga <= 0:
        return None
    return (fgm + 0.5 * three_pm) / fga


def calculate_player_performance_rating(
    points: int = 0,
    rebounds: int = 0,
    assists: int = 0,
    steals: int = 0,
    blocks: int = 0,
    turnovers: int = 0,
    fouls: int = 0,
    plus_minus: int = 0,
    minutes: float = 0.0,
    field_goals_made: int = 0,
    field_goals_attempted: int = 0,
    three_pointers_made: int = 0,
    free_throws_made: int = 0,
    free_throws_attempted: int = 0,
) -> tuple[float, str, bool]:
    """
    Calcula nota 0-10 do jogador no jogo atual.

    Returns:
        (rating, label, low_confidence)

    Labels:
        rating >= 8.5 → "Excelente"
        rating >= 7.0 → "Bom"
        rating >= 5.0 → "Regular"
        rating >  0   → "Ruim"
        rating == 0   → "N/A" (jogador não entrou em quadra)
    """
    # Quem não jogou nada não recebe nota.
    if minutes <= 0 and points == 0 and rebounds == 0 and assists == 0:
        return (0.0, "N/A", True)

    # ── Componente 1: produção bruta ponderada ─────────────────────────────
    raw = (
        points * _RATING_WEIGHTS["points"]
        + rebounds * _RATING_WEIGHTS["rebounds"]
        + assists * _RATING_WEIGHTS["assists"]
        + steals * _RATING_WEIGHTS["steals"]
        + blocks * _RATING_WEIGHTS["blocks"]
        + turnovers * _RATING_WEIGHTS["turnovers"]
        + fouls * _RATING_WEIGHTS["fouls"]
        + plus_minus * _RATING_WEIGHTS["plus_minus"]
    )

    # ── Componente 2: bônus/penalidade de eficiência de arremesso ──────────
    efg = _effective_field_goal_pct(
        field_goals_made, field_goals_attempted, three_pointers_made
    )
    if efg is not None:
        raw += (efg - _EFG_NEUTRAL) * _EFG_WEIGHT

    # ── Componente 3: bônus de free-throw ──────────────────────────────────
    # Quem vai pra linha e converte ganha um pequeno bônus (causa falta +
    # converte). Quem perde lance livre tem leve penalidade.
    if free_throws_attempted > 0:
        ft_pct = free_throws_made / free_throws_attempted
        raw += (ft_pct - 0.75) * 1.0  # 75% é a média NBA aproximada

    # ── Normalização: mapeia raw pra 0–10 ──────────────────────────────────
    # Calibração empírica:
    #   raw = 0  → ~5.0 (jogador médio com pouca produção)
    #   raw = 10 → ~7.0 (jogador sólido)
    #   raw = 20 → ~8.5 (destaque do jogo)
    #   raw = 30 → ~9.5 (monstro)
    rating = 5.0 + raw * 0.18

    # ── Penalidade de minutos curtos ───────────────────────────────────────
    low_confidence = minutes < LOW_CONFIDENCE_MINUTES
    if low_confidence and minutes > 0:
        # Não escapa de receber nota alta jogando 3 minutos
        rating = min(rating, LOW_CONFIDENCE_CAP)

    # ── Clamp final em [0, 10] ─────────────────────────────────────────────
    rating = max(0.0, min(10.0, rating))
    rating = round(rating, 1)

    # ── Label ──────────────────────────────────────────────────────────────
    if rating >= 8.5:
        label = "Excelente"
    elif rating >= 7.0:
        label = "Bom"
    elif rating >= 5.0:
        label = "Regular"
    elif rating > 0:
        label = "Ruim"
    else:
        label = "N/A"

    return (rating, label, low_confidence)
