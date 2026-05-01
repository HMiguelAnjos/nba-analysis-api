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
