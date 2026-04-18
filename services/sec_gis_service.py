"""
SEC GIS Service — Resolución de distribuidora por coordenadas GPS.

Flujo:
  1. Recibe (lat, lon).
  2. Llama a Nominatim (reverse geocode) → extrae nombre de comuna.
  3. Normaliza el nombre.
  4. Consulta caché SQLite (sec_cache) — TTL 180 días.
  5. Si miss: busca en comunas_map.json → distribuidora_id.
  6. Guarda en caché y retorna resultado.
"""

import json
import unicodedata
import urllib.request
from datetime import date, timedelta
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent / "config"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_NOMINATIM_HEADERS = {
    "User-Agent": "CuentaLuz-Chile/1.0 (calculadora boleta electrica; github.com/cuentaluz)"
}
_TTL_DIAS = 180


def _normalizar(s: str) -> str:
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode().strip()


def _cargar_comunas() -> list:
    with open(_BASE / "comunas_map.json", encoding="utf-8") as f:
        return json.load(f)["comunas"]


def _resolver_distribuidora_local(nombre_comuna: str) -> str | None:
    """Busca la distribuidora en comunas_map.json, tolerante a tildes/mayúsculas."""
    target = _normalizar(nombre_comuna)
    for c in _cargar_comunas():
        if _normalizar(c["nombre"]) == target or c["slug"] == target.replace(" ", "-"):
            return c["distribuidora_id"]
    return None


def _nominatim_reverse(lat: float, lon: float) -> dict:
    """Llama a Nominatim reverse geocoding y retorna el JSON de respuesta."""
    url = f"{_NOMINATIM_URL}?lat={lat}&lon={lon}&format=json&addressdetails=1"
    req = urllib.request.Request(url, headers=_NOMINATIM_HEADERS)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extraer_comuna(nominatim_data: dict) -> str | None:
    """
    Extrae el nombre de la comuna del resultado Nominatim.
    En Chile la jerarquía es: city → town → village → suburb → county.
    """
    address = nominatim_data.get("address", {})
    for campo in ("city", "town", "village", "suburb", "county"):
        if campo in address:
            return address[campo]
    return None


def resolver_por_coordenadas(lat: float, lon: float, db=None) -> dict:
    """
    Retorna la distribuidora a partir de coordenadas GPS.

    Retorno exitoso:
        {"distribuidora_id": str, "comuna": str, "fuente": "nominatim" | "cache"}

    Retorno de error:
        {"error": str}

    Args:
        lat: Latitud (-90 a 90).
        lon: Longitud (-180 a 180).
        db:  Sesión SQLAlchemy (opcional). Si se pasa, activa caché SQLite de 180 días.
    """
    # 1. Reverse geocode via Nominatim
    try:
        nominatim_data = _nominatim_reverse(lat, lon)
    except Exception as exc:
        return {"error": f"Nominatim no disponible: {exc}"}

    comuna = _extraer_comuna(nominatim_data)
    if not comuna:
        return {"error": "No se pudo determinar la comuna desde las coordenadas"}

    comuna_norm = _normalizar(comuna)

    # 2. Consultar caché SQLite (si se entregó sesión de DB)
    if db is not None:
        from app.models.sec_cache import SecCache
        cached = db.query(SecCache).filter(
            SecCache.comuna_normalizada == comuna_norm
        ).first()
        if cached:
            limite_ttl = date.today() - timedelta(days=_TTL_DIAS)
            if cached.fecha_consulta >= limite_ttl:
                return {
                    "distribuidora_id": cached.distribuidora_id,
                    "comuna": comuna,
                    "fuente": "cache",
                }
            # Entrada expirada → eliminar para reusar
            db.delete(cached)
            db.commit()

    # 3. Resolver desde mapa local
    dist_id = _resolver_distribuidora_local(comuna)
    if not dist_id:
        return {"error": f"Comuna '{comuna}' no reconocida en el mapa de distribuidoras"}

    # 4. Guardar en caché
    if db is not None:
        from app.models.sec_cache import SecCache
        entry = SecCache(
            comuna_normalizada=comuna_norm,
            distribuidora_id=dist_id,
            fecha_consulta=date.today(),
            fuente="nominatim",
        )
        db.add(entry)
        try:
            db.commit()
        except Exception:
            db.rollback()

    return {
        "distribuidora_id": dist_id,
        "comuna": comuna,
        "fuente": "nominatim",
    }
