import os

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# Modo desktop (Electron): o renderer pode ter origin "null" (file://) ou
# http://localhost:<porta-vite>. Como a API só escuta em 127.0.0.1, liberar
# todas as origens é seguro nesse contexto.
#
# Em produção cloud use origens explícitas:
#   ALLOWED_ORIGINS=https://meusite.com,https://www.meusite.com
_raw = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:5174,http://localhost:3000,null,*",
)
# Se a variável for literalmente "*", libera tudo; caso contrário, lista normal
if _raw.strip() == "*":
    ALLOWED_ORIGINS: list[str] = ["*"]
else:
    ALLOWED_ORIGINS = [o.strip() for o in _raw.split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------
PORT: int = int(os.getenv("PORT", "8000"))

# Em modo desktop a API deve escutar SOMENTE em localhost
HOST: str = os.getenv("HOST", "127.0.0.1")

# Optional HTTP proxy for stats.nba.com (blocked on cloud IPs without one)
# Ex: STATS_PROXY=http://user:pass@host:port
STATS_PROXY: str | None = os.getenv("STATS_PROXY") or None

# Live games worker
ENABLE_LIVE_WORKER: bool = os.getenv("ENABLE_LIVE_WORKER", "true").lower() == "true"
LIVE_POLL_INTERVAL_MS: int = int(os.getenv("LIVE_POLL_INTERVAL_MS", "2000"))

# ---------------------------------------------------------------------------
# Modo fixture (testar offline / sem jogos ao vivo)
# ---------------------------------------------------------------------------
# Setar USE_FIXTURES=1 faz o live_game_service ler de tests/fixtures/ em
# vez de bater na NBA Live API. Útil pra dev quando não tem jogo rolando.
USE_FIXTURES: bool = os.getenv("USE_FIXTURES", "0") == "1"
