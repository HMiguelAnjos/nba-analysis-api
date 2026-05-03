"""
Background worker that pre-warms the season-averages cache for players in
today's games.

Why:
    stats.nba.com periodically blocks cloud IPs (Railway/AWS/etc). When a
    user clicks a game and we hit stats.nba.com on the request path, the
    request can hang or fail. By pre-fetching season averages on startup
    and on a periodic schedule, the PersistentCache will be warm before
    any user request — so user-facing requests never depend on
    stats.nba.com being available right that second.

How it works:
    - On startup (after a short delay to let the live games worker populate
      its cache) and every WARM_INTERVAL_S seconds afterwards, walks the
      list of today's games.
    - For each game that has already started (in_progress or final), reads
      its boxscore and calls _get_season_averages for every player.
    - Cache hits are no-ops; cache misses populate the PersistentCache with
      a 24h TTL. Failures are silently retried on the next cycle.

Guarantees:
    - Single instance per process (guarded by _warmer_started).
    - Errors never crash the application.
    - Skips not_started games (no boxscore rosters available yet).
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.cache.live_games_cache import AbstractLiveGamesCache
from src.services.live_analysis_service import LiveAnalysisService
from src.services.live_game_service import LiveGameService

logger = logging.getLogger(__name__)

_warmer_started = False


async def start_season_cache_warmer(
    live_cache: AbstractLiveGamesCache,
    live_game: LiveGameService,
    live_analysis: LiveAnalysisService,
    season: str,
    warm_interval_s: int = 1800,    # 30 min
    initial_delay_s: int = 30,      # let live games worker populate first
) -> None:
    """Launch the warmer as a long-running asyncio task. Call once on startup."""
    global _warmer_started
    if _warmer_started:
        logger.warning("Season cache warmer already running — skipping duplicate start.")
        return
    _warmer_started = True
    asyncio.create_task(
        _run(live_cache, live_game, live_analysis, season, warm_interval_s, initial_delay_s),
        name="season_cache_warmer",
    )
    logger.info(
        "Season cache warmer scheduled (initial=%ds, interval=%ds, season=%s).",
        initial_delay_s, warm_interval_s, season,
    )


async def _run(
    live_cache: AbstractLiveGamesCache,
    live_game: LiveGameService,
    live_analysis: LiveAnalysisService,
    season: str,
    warm_interval_s: int,
    initial_delay_s: int,
) -> None:
    """Main warmer loop. Runs indefinitely until cancelled."""
    await asyncio.sleep(initial_delay_s)

    while True:
        try:
            await asyncio.to_thread(_warm_once, live_cache, live_game, live_analysis, season)
        except asyncio.CancelledError:
            logger.info("Season cache warmer shutting down.")
            raise
        except Exception as exc:
            logger.error("Cache warmer cycle failed (will retry): %s", exc)

        await asyncio.sleep(warm_interval_s)


def _warm_once(
    live_cache: AbstractLiveGamesCache,
    live_game: LiveGameService,
    live_analysis: LiveAnalysisService,
    season: str,
) -> None:
    """Single warming pass over today's games. Synchronous (runs in thread)."""
    snapshot = live_cache.get_snapshot()
    if snapshot is None:
        logger.info("Warmer: no live games snapshot yet — skipping cycle.")
        return

    games = [g for g in snapshot.data.games if g.game_status in ("in_progress", "final")]
    if not games:
        logger.info("Warmer: no in-progress/final games today — nothing to warm.")
        return

    # Collect unique player IDs across all relevant games via boxscores.
    player_ids: set[int] = set()
    for g in games:
        try:
            bs = live_game.get_live_boxscore(g.game_id)
            for team in (bs.home_team, bs.away_team):
                for p in team.players:
                    player_ids.add(p.player_id)
        except Exception as exc:
            logger.warning("Warmer: could not fetch boxscore for %s: %s", g.game_id, exc)

    if not player_ids:
        logger.info("Warmer: no players found in today's boxscores.")
        return

    logger.info(
        "Warmer: starting season-avg pre-fetch for %d unique players across %d games.",
        len(player_ids), len(games),
    )

    warmed = 0
    failed = 0
    # Reuse the same parallel-fetch pattern as the live analysis path.
    with ThreadPoolExecutor(max_workers=min(len(player_ids), 16)) as pool:
        futures = {
            pool.submit(live_analysis._get_season_averages, pid, season): pid
            for pid in player_ids
        }
        for fut in as_completed(futures):
            try:
                if fut.result() is not None:
                    warmed += 1
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                logger.debug("Warmer: player %d failed: %s", futures[fut], exc)

    logger.info(
        "Warmer: cycle complete — %d cached, %d failed (will retry next cycle).",
        warmed, failed,
    )
