"""
services/tarifa_service.py — Capa de servicio tarifario.

Expone la interfaz limpia que usan las rutas y el updater:
  get_distribuidora(comuna)          → str | None
  get_tarifa(comuna, tipo)           → dict
  calcular_boleta(comuna, tipo, kwh) → dict (desglose completo)
  get_metadata()                     → dict (vigencia, staleness, alerta)
  get_historico(distribuidora, meses)→ list[dict]
"""
import json
import unicodedata
from datetime import date
from pathlib import Path
from typing import Optional

_ROOT         = Path(__file__).resolve().parent.parent
_TARIFAS_PATH = _ROOT / "config" / "tarifas.json"
_COMUNAS_PATH = _ROOT / "config" / "comunas_map.json"
_HISTORICO    = _ROOT / "data" / "tarifas_historico.json"

_ALERTA_DIAS = 45   # mostrar advertencia si datos tienen mas de N dias


# ── I/O ──────────────────────────────────────────────────────────────────────

def _cargar_tarifas() -> dict:
    with open(_TARIFAS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _cargar_comunas() -> list:
    """Devuelve la lista de comunas desde config/comunas_map.json."""
    with open(_COMUNAS_PATH, encoding="utf-8") as f:
        return json.load(f)["comunas"]


def _cargar_historico() -> list:
    with open(_HISTORICO, encoding="utf-8") as f:
        return json.load(f)


def _normalizar(texto: str) -> str:
    return unicodedata.normalize("NFD", texto.lower().strip()).encode("ascii", "ignore").decode()


# ── API publica ───────────────────────────────────────────────────────────────

def get_distribuidora(comuna: str) -> Optional[str]:
    """
    Resuelve el nombre de una comuna a su distribuidora_id.
    Tolerante a tildes y mayusculas.
    """
    comunas = _cargar_comunas()
    target = _normalizar(comuna)
    for c in comunas:
        if _normalizar(c["nombre"]) == target:
            return c["distribuidora_id"]
    return None


def get_tarifa(comuna: str, tipo: str = "BT1") -> dict:
    """
    Devuelve el dict de componentes tarifarios para una comuna y tipo.
    Lanza ValueError si la comuna no se reconoce.
    """
    dist_id = get_distribuidora(comuna)
    if not dist_id:
        raise ValueError(f"Comuna '{comuna}' no reconocida en el mapa de distribuidoras")
    tarifas = _cargar_tarifas()
    dist = tarifas.get(dist_id, {})
    tarifa = dist.get("tarifas", {}).get(tipo)
    if not tarifa:
        raise ValueError(f"Tarifa {tipo} no disponible para {dist_id}")
    return tarifa


def calcular_boleta(
    comuna: str,
    tipo: str,
    kwh_consumo: float,
    demanda_punta_kw: float = 1.5,
) -> dict:
    """
    Calcula el desglose completo de la boleta para una comuna.
    Delega en app.services.calculator_service.calcular_boleta.
    """
    dist_id = get_distribuidora(comuna)
    if not dist_id:
        raise ValueError(f"Comuna '{comuna}' no reconocida")
    from app.services.calculator_service import calcular_boleta as _calc
    return _calc(kwh_consumo, dist_id, tipo, demanda_punta_kw)


def get_metadata() -> dict:
    """
    Devuelve metadata global de vigencia + indicadores de staleness.

    Campos adicionales calculados:
      dias_desde_actualizacion: int
      alerta_desactualizado:    bool  (> 45 dias)
      proxima_actualizacion:    str   (ISO date)
    """
    tarifas = _cargar_tarifas()
    meta = dict(tarifas.get("metadata", {}))

    ultima = meta.get("ultima_actualizacion")
    if ultima:
        try:
            dias = (date.today() - date.fromisoformat(ultima)).days
            meta["dias_desde_actualizacion"] = dias
            meta["alerta_desactualizado"]    = dias > _ALERTA_DIAS
        except ValueError:
            meta["dias_desde_actualizacion"] = None
            meta["alerta_desactualizado"]    = False

    # Proxima actualizacion: primer dia del siguiente semestre si no esta definida
    if not meta.get("proxima_actualizacion"):
        hoy = date.today()
        if hoy.month <= 6:
            proxima = date(hoy.year, 10, 1)
        else:
            proxima = date(hoy.year + 1, 4, 1)
        meta["proxima_actualizacion"] = proxima.isoformat()

    return meta


def get_historico(distribuidora: str, meses: int = 12) -> list:
    """
    Devuelve las ultimas `meses` entradas del historico para una distribuidora.
    """
    historico = _cargar_historico()
    entradas = [
        h for h in historico
        if h.get("distribuidora_id") == distribuidora
    ]
    return entradas[-meses:]
