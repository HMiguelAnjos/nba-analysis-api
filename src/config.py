import os

# Origens permitidas: separe múltiplas URLs por vírgula na variável de ambiente
# Ex: ALLOWED_ORIGINS=https://meusite.com,https://www.meusite.com
_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:3000")
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw.split(",") if o.strip()]

PORT: int = int(os.getenv("PORT", "8000"))
