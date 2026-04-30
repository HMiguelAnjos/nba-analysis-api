"""
LiveWorker
----------
Task assíncrona que roda em background e pré-popula o cache de dados ao vivo
a cada WORKER_INTERVAL segundos.

Fluxo por ciclo
~~~~~~~~~~~~~~~
1. Busca o scoreboard de hoje  → popula cache do LiveGameService
2. Para cada jogo ao vivo (status == "live"), busca o boxscore
   → popula cache do LiveGameService
3. Registra timestamp da última atualização e quantidade de jogos cacheados
4. Se a NBA API falhar, mantém o último cache válido (a falha fica nos erros)
5. Nunca derruba a aplicação por erro externo
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.services.live_game_service import LiveGameService

logger = logging.getLogger(__name__)

WORKER_INTERVAL: int = 5   # segundos entre cada ciclo
MAX_ERRORS: int = 20        # quantidade máxima de erros guardados em memória


class LiveWorker:
    """Worker que pré-popula o cache de dados live em intervalos regulares."""

    def __init__(self, live_game: LiveGameService) -> None:
        self._live = live_game
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._last_update: Optional[datetime] = None
        self._games_cached: int = 0
        self._errors: list[str] = []

    # ------------------------------------------------------------------ #
    # Controle de ciclo de vida                                             #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Inicia o loop em background (idempotente)."""
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="live-worker")
        logger.info("LiveWorker iniciado (intervalo=%ds)", WORKER_INTERVAL)

    def stop(self) -> None:
        """Para o loop de forma limpa."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("LiveWorker encerrado")

    # ------------------------------------------------------------------ #
    # Estado público – usado pelo endpoint /live/cache/status              #
    # ------------------------------------------------------------------ #

    def status(self) -> dict:
        now = datetime.now(timezone.utc)
        last_str = self._last_update.isoformat() if self._last_update else None

        if self._last_update:
            elapsed = (now - self._last_update).total_seconds()
            next_in = round(max(0.0, WORKER_INTERVAL - elapsed), 1)
        else:
            next_in = float(WORKER_INTERVAL)

        return {
            "status": "running" if self._running else "stopped",
            "last_update": last_str,
            "next_update_in_seconds": next_in,
            "games_cached": self._games_cached,
            "errors": self._errors[-5:],   # só os 5 erros mais recentes
        }

    # ------------------------------------------------------------------ #
    # Loop interno                                                          #
    # ------------------------------------------------------------------ #

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._fetch_all()
                self._last_update = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._record_error(exc)
            await asyncio.sleep(WORKER_INTERVAL)

    async def _fetch_all(self) -> None:
        """Um ciclo completo de fetch: scoreboard + boxscores dos jogos live."""
        loop = asyncio.get_event_loop()

        # 1. Scoreboard ─ se falhar, propaga para _loop registrar o erro
        games_data = await loop.run_in_executor(None, self._live.get_today_games)

        live_games = [g for g in games_data.games if g.game_status == "live"]
        cached_count = 0

        # 2. Boxscore de cada jogo ao vivo
        for game in live_games:
            try:
                await loop.run_in_executor(
                    None, self._live.get_live_boxscore, game.game_id
                )
                cached_count += 1
            except Exception as exc:
                # Erro em um boxscore não cancela os demais
                self._record_error(exc, prefix=f"boxscore {game.game_id}")

        self._games_cached = cached_count
        logger.debug("Worker tick: %d jogos ao vivo cacheados", cached_count)

    # ------------------------------------------------------------------ #
    # Auxiliares                                                            #
    # ------------------------------------------------------------------ #

    def _record_error(self, exc: Exception, prefix: str = "") -> None:
        label = f"{prefix}: " if prefix else ""
        msg = f"[{datetime.now(timezone.utc).isoformat()}] {label}{exc}"
        self._errors.append(msg)
        if len(self._errors) > MAX_ERRORS:
            self._errors = self._errors[-MAX_ERRORS:]
        logger.error("LiveWorker %s", msg)
