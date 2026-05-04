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
