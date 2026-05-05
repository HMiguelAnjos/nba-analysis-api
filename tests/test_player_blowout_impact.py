"""
Testes para calculate_player_blowout_impact.

Verifica que a flag "Risco de descanso" só aparece pros jogadores certos:
- titulares e jogadores de alta minutagem em jogos com blowout brewing
- NUNCA em fim de banco (eles GANHAM minutos no garbage time)
- NUNCA quando jogo não está em risco de blowout
"""
from src.utils.stats import calculate_player_blowout_impact


# ─── Sem blowout ────────────────────────────────────────────────────────────

def test_no_blowout_starter_high_minutes_no_flag():
    """Jogo equilibrado: nem titular com 30 min recebe flag."""
    result = calculate_player_blowout_impact(
        player_minutes=30, is_starter=True,
        game_blowout_pct=15, game_blowout_level="low",
    )
    assert result is None


def test_no_blowout_below_floor():
    """blowout_pct abaixo de 30% nunca dispara flag."""
    result = calculate_player_blowout_impact(
        player_minutes=35, is_starter=True,
        game_blowout_pct=29, game_blowout_level="low",
    )
    assert result is None


# ─── Jogo finalizado ────────────────────────────────────────────────────────

def test_final_game_no_flag():
    """Jogo encerrado: nunca tem mais minutos a perder."""
    result = calculate_player_blowout_impact(
        player_minutes=35, is_starter=True,
        game_blowout_pct=80, game_blowout_level="final",
    )
    assert result is None


# ─── Reservas de fim de banco (NÃO devem ganhar flag) ──────────────────────

def test_low_minute_bench_no_flag_even_with_high_blowout():
    """Cara de fim de banco com 6 min: blowout favorece ele, sem flag."""
    result = calculate_player_blowout_impact(
        player_minutes=6, is_starter=False,
        game_blowout_pct=85, game_blowout_level="high",
    )
    assert result is None


def test_zero_minute_bench_no_flag():
    """Reserva que não entrou: não tem como perder o que não tem."""
    result = calculate_player_blowout_impact(
        player_minutes=0, is_starter=False,
        game_blowout_pct=70, game_blowout_level="high",
    )
    assert result is None


def test_below_threshold_bench_no_flag():
    """Reserva com 17 min (abaixo do threshold de 18): sem flag."""
    result = calculate_player_blowout_impact(
        player_minutes=17, is_starter=False,
        game_blowout_pct=75, game_blowout_level="high",
    )
    assert result is None


# ─── Titulares com blowout (DEVEM ganhar flag) ─────────────────────────────

def test_starter_high_minutes_high_blowout_high_level():
    """Titular com 28 min em blowout 75%: nivel HIGH."""
    result = calculate_player_blowout_impact(
        player_minutes=28, is_starter=True,
        game_blowout_pct=75, game_blowout_level="high",
    )
    assert result is not None
    assert result["applies"] is True
    assert result["level"] == "high"
    assert "Titular" in result["reason"]


def test_starter_low_minutes_high_blowout_medium_level():
    """Titular com 19 min em blowout alto: medium (jogou pouco até agora)."""
    result = calculate_player_blowout_impact(
        player_minutes=19, is_starter=True,
        game_blowout_pct=70, game_blowout_level="high",
    )
    assert result is not None
    assert result["level"] == "medium"


def test_starter_medium_blowout_medium_level():
    """Titular num jogo com blowout 50%: nivel medium."""
    result = calculate_player_blowout_impact(
        player_minutes=25, is_starter=True,
        game_blowout_pct=50, game_blowout_level="medium",
    )
    assert result is not None
    assert result["level"] == "medium"


def test_starter_low_blowout_low_level():
    """Titular num jogo com blowout 35%: nivel low (mas marca)."""
    result = calculate_player_blowout_impact(
        player_minutes=24, is_starter=True,
        game_blowout_pct=35, game_blowout_level="medium",
    )
    assert result is not None
    assert result["level"] == "low"


# ─── Reservas de alta minutagem (devem ganhar flag também) ─────────────────

def test_high_minute_bench_gets_flag_in_high_blowout():
    """Reserva com 25 min (6º homem) em blowout alto: flag de medium."""
    result = calculate_player_blowout_impact(
        player_minutes=25, is_starter=False,
        game_blowout_pct=75, game_blowout_level="high",
    )
    assert result is not None
    assert result["applies"] is True
    # Não-titular nunca pega "high", mesmo com muitos minutos
    assert result["level"] == "medium"


def test_just_at_minute_threshold():
    """Reserva exatamente no limiar de 18 min: pega flag em blowout alto."""
    result = calculate_player_blowout_impact(
        player_minutes=18, is_starter=False,
        game_blowout_pct=70, game_blowout_level="high",
    )
    assert result is not None
    assert result["level"] == "medium"
