"""
Testes para calculate_fair_line e calculate_edge_decision.

A linha estimada é o coração do synthetic bookmaker. Garantir que:
- Os pesos refletem corretamente forma recente vs temporada
- Arredondamento bate com o formato típico de mercado (.5)
- Linhas mínimas / edges extremos não geram lixo
- Decisões de edge mapeiam direto pros 5 estados de aposta
"""
from src.utils.stats import calculate_edge_decision, calculate_fair_line


# ─── calculate_fair_line ────────────────────────────────────────────────────

def test_consistent_player_line_matches_average():
    """Player que faz exatamente a média em todos os splits = linha ≈ avg − vig."""
    line = calculate_fair_line(season_avg=20.0, last_10_avg=20.0, last_5_avg=20.0)
    # blend = 20, − 0.5 vig = 19.5
    assert line == 19.5


def test_hot_streak_pushes_line_up():
    """Forma recente acima da média deve subir a linha."""
    cold_line = calculate_fair_line(season_avg=15.0, last_10_avg=15.0, last_5_avg=15.0)
    hot_line  = calculate_fair_line(season_avg=15.0, last_10_avg=18.0, last_5_avg=22.0)
    assert hot_line > cold_line
    # blend = 0.3*15 + 0.4*18 + 0.3*22 = 4.5 + 7.2 + 6.6 = 18.3, − 0.5 = 17.8 → 18.0 (.5 mais próximo)
    assert hot_line == 18.0


def test_cold_streak_pulls_line_down():
    """Forma ruim recente puxa a linha pra baixo."""
    line = calculate_fair_line(season_avg=18.0, last_10_avg=14.0, last_5_avg=10.0)
    # blend = 5.4 + 5.6 + 3.0 = 14.0, − 0.5 = 13.5
    assert line == 13.5


def test_low_volume_player_has_minimum_line():
    """Reserva de fim de banco com 0.2 ppg não vai ter linha de 0 ou negativa."""
    line = calculate_fair_line(season_avg=0.2, last_10_avg=0.1, last_5_avg=0.0)
    assert line >= 0.5
    assert line == 0.5


def test_rounding_to_half():
    """Sempre arredonda pro .5 mais próximo, formato padrão de bookmaker."""
    cases = [
        # (season, last_10, last_5) → expected_line
        # blend = 0.3*s + 0.4*l10 + 0.3*l5 ; line = round(blend - 0.5 to .5)
        ((4.0, 4.0, 4.0),    3.5),  # blend=4.0, -0.5=3.5 → 3.5
        ((10.0, 11.0, 12.0), 10.5),  # blend=11.0, -0.5=10.5 → 10.5
        ((25.0, 28.0, 30.0), 27.0),  # blend=27.7, -0.5=27.2 → 27.0
    ]
    for (s, l10, l5), expected in cases:
        line = calculate_fair_line(s, l10, l5)
        assert line == expected, f"({s},{l10},{l5}) → esperado {expected}, veio {line}"


# ─── calculate_edge_decision ────────────────────────────────────────────────

def test_strong_over_at_two_or_more():
    assert calculate_edge_decision(2.0) == "STRONG_OVER"
    assert calculate_edge_decision(3.5) == "STRONG_OVER"
    assert calculate_edge_decision(10.0) == "STRONG_OVER"


def test_lean_over_one_to_two():
    assert calculate_edge_decision(1.0) == "LEAN_OVER"
    assert calculate_edge_decision(1.5) == "LEAN_OVER"
    assert calculate_edge_decision(1.9) == "LEAN_OVER"


def test_neutral_zone():
    assert calculate_edge_decision(0.0) == "NEUTRAL"
    assert calculate_edge_decision(0.5) == "NEUTRAL"
    assert calculate_edge_decision(-0.9) == "NEUTRAL"
    assert calculate_edge_decision(0.99) == "NEUTRAL"


def test_lean_under_negative():
    assert calculate_edge_decision(-1.0) == "LEAN_UNDER"
    assert calculate_edge_decision(-1.5) == "LEAN_UNDER"


def test_strong_under_at_two_or_less():
    assert calculate_edge_decision(-2.0) == "STRONG_UNDER"
    assert calculate_edge_decision(-3.5) == "STRONG_UNDER"


# ─── Cenários reais combinados ──────────────────────────────────────────────

def test_marcus_smart_realistic_scenario():
    """
    Real: Marcus Smart AST. Season 4.0, last_10 4.5, last_5 5.2.
    blend = 1.2 + 1.8 + 1.56 = 4.56, -0.5 = 4.06 → linha 4.0.
    Projeção fim 7 → edge +3.0 → STRONG_OVER.
    """
    line = calculate_fair_line(season_avg=4.0, last_10_avg=4.5, last_5_avg=5.2)
    assert line == 4.0
    edge = round(7.0 - line, 1)  # 3.0
    assert calculate_edge_decision(edge) == "STRONG_OVER"


def test_role_player_no_edge():
    """
    Player com forma estável e projeção bate na linha → sem edge → NEUTRAL.
    Ex: cara fazendo 8 ppg constante, projeção 7.8.
    """
    line = calculate_fair_line(season_avg=8.0, last_10_avg=8.2, last_5_avg=7.9)
    # blend = 2.4 + 3.28 + 2.37 = 8.05, − 0.5 = 7.55 → 7.5
    assert line == 7.5
    edge = round(7.8 - line, 1)  # 0.3
    assert calculate_edge_decision(edge) == "NEUTRAL"


def test_underperforming_player_under_signal():
    """
    Player projetado a finalizar bem abaixo da linha → STRONG_UNDER.
    """
    line = calculate_fair_line(season_avg=20.0, last_10_avg=22.0, last_5_avg=24.0)
    # blend = 6 + 8.8 + 7.2 = 22, -0.5 = 21.5
    assert line == 21.5
    # Jogador caminha pra 18 (foul trouble, blowout, etc.)
    edge = round(18.0 - line, 1)  # -3.5
    assert calculate_edge_decision(edge) == "STRONG_UNDER"
