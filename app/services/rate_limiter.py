"""
Rate limiter en memoria — simple, sin dependencias externas.
Válido para despliegue con un solo worker (Railway/Render).
"""
from collections import defaultdict
from time import time

_store: dict[str, list[float]] = defaultdict(list)


def allow(key: str, limit: int, window: int) -> bool:
    """
    Retorna True si la solicitud está dentro del límite.
    key    : identificador único (ej. "tips:1.2.3.4")
    limit  : máximo de solicitudes permitidas en el ventana
    window : ventana de tiempo en segundos
    """
    now   = time()
    calls = [t for t in _store[key] if now - t < window]
    _store[key] = calls
    if len(calls) >= limit:
        return False
    _store[key].append(now)
    return True


def client_ip(request) -> str:
    """Extrae IP real considerando proxies (Railway usa X-Forwarded-For)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host or "unknown"
