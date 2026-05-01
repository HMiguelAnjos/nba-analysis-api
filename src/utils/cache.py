import time
from typing import Any, Optional


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
