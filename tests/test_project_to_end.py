"""
Testes para _project_to_end.

Cobre o fix do bug do Barnes (jogo finalizado não pode extrapolar) e
casos típicos: pouco jogado, ritmo quente, blowout, fouls.
"""
from src.services.live_analysis_service import LiveAnalysisService

project = LiveAnalysisService._project_to_end


def test_final_game_returns_actual_stat_no_extrapolation():
    """
    Bug do Barnes: jogador com 4 reb em 6 minutos não pode projetar 9.9
    quando o jogo já acabou. Final = stat real, sem margem nenhuma.
    """
    low, expected, high = project(
        stat=4, minutes=6, avg_stat=5.0, avg_minutes=30.0,
        is_final=True,
    )
    assert low == 4.0
    assert expected == 4.0
    assert high == 4.0


def test_final_game_with_zero_minutes_player():
    """Reserva que não jogou em jogo final = 0 stat sem extrapolação."""
    low, expected, high = project(
        stat=0, minutes=0, avg_stat=10.0, avg_minutes=20.0,
        is_final=True,
    )
    assert (low, expected, high) == (0.0, 0.0, 0.0)


def test_zero_minutes_returns_zero():
    """Jogador que ainda não entrou em quadra (live)."""
    assert project(stat=0, minutes=0, avg_stat=20.0, avg_minutes=30.0) == (0.0, 0.0, 0.0)


def test_live_game_extrapolates():
    """Live: jogador no Q2 com produção típica → projeção razoável."""
    low, expected, high = project(
        stat=10, minutes=15, avg_stat=20.0, avg_minutes=32.0,
        period=2, game_minutes_remaining=24.0,
    )
    # Deve projetar perto do dobro do que ele já fez (mais ou menos)
    assert expected >= 10.0
    assert expected <= 25.0
    assert low <= expected <= high


def test_low_minutes_hot_pace_capped():
    """
    Cara fez 4 reb em 6 min num jogo ainda rolando — não pode projetar 25.
    A função deve limitar com weight da temporada e margem.
    """
    low, expected, high = project(
        stat=4, minutes=6, avg_stat=5.0, avg_minutes=30.0,
        period=1, game_minutes_remaining=42.0,
    )
    # Cap deve ficar em ~max(5*1.8, 5+5) = 10
    assert expected <= 10.5


def test_javonte_case_low_avg_quick_start_no_inflation():
    """
    Regressão real: Javonte Green (avg 6.9 pts em 17.6 min) com 3 pts em 3 min.
    Antes a fórmula projetava 15.2 — quase 2.2× a média histórica. Com cap
    + shrinkage para a média em amostra pequena, deve ficar perto da média
    com leve uptick (8-10 pts).
    """
    low, expected, high = project(
        stat=3, minutes=3, avg_stat=6.9, avg_minutes=17.6,
        period=2, game_minutes_remaining=24.0,
    )
    # Após shrinkage: ~12.4 * 0.375 + 6.9 * 0.625 ≈ 8.95
    assert expected <= 10.0, f"Esperado <=10, veio {expected}"
    assert expected >= 4.0, f"Esperado >=4 (não pode regredir abaixo do que ele já tem), veio {expected}"


def test_shrinkage_disabled_after_8_min():
    """Após ~8 min, shrinkage não age — projeção é a do ritmo + cap."""
    _, expected_early, _ = project(
        stat=10, minutes=4, avg_stat=10.0, avg_minutes=30.0,
        period=2, game_minutes_remaining=28.0,
    )
    _, expected_later, _ = project(
        stat=10, minutes=10, avg_stat=10.0, avg_minutes=30.0,
        period=2, game_minutes_remaining=24.0,
    )
    # Aos 10 min sem shrinkage: deve projetar mais (mais info, mais confiança no ritmo)
    assert expected_later >= expected_early - 1.0


def test_shrinkage_only_when_hot():
    """Ritmo normal/baixo nem é tocado pelo shrinkage."""
    # Jogador fazendo média na média: shrinkage não aplica
    _, expected, _ = project(
        stat=2, minutes=4, avg_stat=15.0, avg_minutes=30.0,  # ritmo 0.5 pts/min vs season 0.5
        period=1, game_minutes_remaining=44.0,
    )
    # Sem shrinkage, projeta 2 + 0.5*~26 = 15. Com shrinkage seria menor.
    # Verifica que ficou no esperado (não foi puxado abaixo).
    assert expected >= 12.0


def test_tobias_case_modest_avg_hot_first_half():
    """
    Tobias Harris (avg ~5.5 reb) com 6 reb em 12 min: projeção não pode
    explodir pra 10+. Cap em ~10.5.
    """
    _, expected, _ = project(
        stat=6, minutes=12, avg_stat=5.5, avg_minutes=30.0,
        period=2, game_minutes_remaining=24.0,
    )
    # Cap: max(5.5*1.8, 5.5+5) = max(9.9, 10.5) = 10.5
    assert expected <= 10.5


def test_blowout_reduces_target_minutes():
    """Blowout severo → menos minutos esperados → projeção menor."""
    no_blowout = project(
        stat=10, minutes=20, avg_stat=20.0, avg_minutes=32.0,
        period=4, game_minutes_remaining=8.0,
        blowout_severity=0.0,
    )
    severe_blowout = project(
        stat=10, minutes=20, avg_stat=20.0, avg_minutes=32.0,
        period=4, game_minutes_remaining=8.0,
        blowout_severity=1.0,
    )
    assert severe_blowout[1] <= no_blowout[1]


def test_already_above_target_no_extrapolation():
    """Jogador que já jogou mais que avg_minutes → sem extrapolar."""
    low, expected, high = project(
        stat=25, minutes=35, avg_stat=20.0, avg_minutes=30.0,
        period=4, game_minutes_remaining=2.0,
    )
    # Não pode projetar muito além de 25
    assert expected <= 27.0


def test_low_never_below_actual():
    """Lower bound nunca pode ser menor que o stat real (não dá pra desfazer)."""
    low, expected, high = project(
        stat=15, minutes=10, avg_stat=8.0, avg_minutes=30.0,
        period=2, game_minutes_remaining=24.0,
    )
    assert low >= 15.0
