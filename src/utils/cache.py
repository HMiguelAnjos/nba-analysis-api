import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SimpleCache:
    """
    In-memory key-value cache com TTL por entrada.

    API pública
    -----------
    set(key, value, ttl)  – grava / atualiza
    get(key)              – retorna valor ou None se expirado/ausente
    has(key)              – True se a chave existe e não expirou
    invalidate(key)       – remove manualmente
    clear()               – limpa tudo
    count_prefix(prefix)  – conta entradas válidas com determinado prefixo
    status()              – diagnóstico resumido
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if time.monotonic() > expiry:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._store[key] = (value, time.monotonic() + ttl)

    def has(self, key: str) -> bool:
        """True se a chave existe e ainda não expirou."""
        return self.get(key) is not None

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove todas as entradas."""
        self._store.clear()

    def count_prefix(self, prefix: str) -> int:
        """Conta entradas válidas cujo nome começa com *prefix*."""
        now = time.monotonic()
        return sum(
            1
            for k, (_, exp) in list(self._store.items())
            if k.startswith(prefix) and exp > now
        )

    def status(self) -> dict:
        now = time.monotonic()
        valid_keys = [k for k, (_, exp) in list(self._store.items()) if exp > now]
        return {"total_entries": len(valid_keys), "keys": valid_keys}


# Alias para retrocompatibilidade
LocalCacheService = SimpleCache


class PersistentCache(SimpleCache):
    """
    SimpleCache com fallback em disco (JSON).

    Ao fazer `set`, grava também em *path* no disco.
    Ao fazer `get` com miss na memória, tenta carregar do disco.

    Isso garante que médias de temporada sobrevivam a restarts do
    container sem precisar chamar stats.nba.com novamente.

    TTL é armazenado como timestamp Unix absoluto no JSON, então
    funciona corretamente entre processos.
    """

    def __init__(self, path: str = "/tmp/nba_season_cache.json") -> None:
        super().__init__()
        self._path = path
        self._disk: dict[str, tuple[Any, float]] = {}
        self._load_disk()

    def _load_disk(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r") as f:
                    raw = json.load(f)
                now = time.time()
                self._disk = {k: (v, exp) for k, (v, exp) in raw.items() if exp > now}
                logger.info("PersistentCache: carregou %d entradas do disco", len(self._disk))
        except Exception as exc:
            logger.warning("PersistentCache: falha ao carregar disco: %s", exc)
            self._disk = {}

    def _save_disk(self) -> None:
        try:
            with open(self._path, "w") as f:
                json.dump(self._disk, f)
        except Exception as exc:
            logger.warning("PersistentCache: falha ao salvar disco: %s", exc)

    def get(self, key: str) -> Optional[Any]:
        # 1. memória
        value = super().get(key)
        if value is not None:
            return value
        # 2. disco
        entry = self._disk.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if time.time() > expiry:
            del self._disk[key]
            return None
        # promove para memória (TTL restante)
        remaining = int(expiry - time.time())
        if remaining > 0:
            super().set(key, value, remaining)
        return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        super().set(key, value, ttl)
        self._disk[key] = (value, time.time() + ttl)
        self._save_disk()
