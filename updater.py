"""
updater.py — Actualización mensual de tarifas eléctricas.

Descarga los PDFs de cada distribuidora, extrae los valores tarifarios
y actualiza config/tarifas.json si hay cambios.

Uso:
    python updater.py                  # todas las distribuidoras
    python updater.py --dist enel      # solo Enel
    python updater.py --dry-run        # muestra cambios sin guardar
    python updater.py --force          # actualiza aunque no haya cambios

Cron mensual (Railway / Render / servidor propio):
    0 6 1 * * cd /app && python updater.py >> logs/updater.log 2>&1
"""
import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

_ROOT     = Path(__file__).resolve().parent
_TARIFAS  = _ROOT / "config" / "tarifas.json"
_LOGS_DIR = _ROOT / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOGS_DIR / "updater.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("updater")

# ── Scrapers disponibles ──────────────────────────────────────────────────────
SCRAPERS = {
    "enel":      "scraper.enel_scraper",
    "cge":       "scraper.cge_scraper",
    "chilquinta":"scraper.chilquinta_scraper",
    "frontel":   "scraper.frontel_scraper",
}

# Campos que se comparan para detectar cambios (solo tarifas BT1/BT2)
_CAMPOS_TARIFA = [
    "cargo_fijo_neto",
    "cargo_servicio_publico_kwh",
    "cargo_transporte_kwh_neto",
    "cargo_energia_kwh_neto",
    "cargo_potencia_kwh_neto",
    "cargo_demanda_punta_kw_mes_neto",
]
_UMBRAL_CAMBIO = 0.5  # CLP o CLP/kWh — diferencia mínima para considerar cambio real


def _cargar_tarifas() -> dict:
    with open(_TARIFAS, encoding="utf-8") as f:
        return json.load(f)


def _guardar_tarifas(data: dict) -> None:
    with open(_TARIFAS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"tarifas.json actualizado → {_TARIFAS}")


def _diff_tarifas(actuales: dict, nuevas: dict) -> list[str]:
    """Devuelve lista de strings describiendo los cambios entre dos sets de tarifas."""
    cambios = []
    for tipo_tarifa in ("BT1", "BT2"):
        act = actuales.get(tipo_tarifa, {})
        nva = nuevas.get(tipo_tarifa, {})
        if not nva:
            continue
        for campo in _CAMPOS_TARIFA:
            v_act = act.get(campo)
            v_nva = nva.get(campo)
            if v_act is None or v_nva is None:
                continue
            if abs(v_act - v_nva) > _UMBRAL_CAMBIO:
                cambios.append(f"  {tipo_tarifa}.{campo}: {v_act} → {v_nva}")
    return cambios


def actualizar_distribuidora(
    dist_id: str,
    tarifas_data: dict,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    """
    Ejecuta el scraper para una distribuidora y actualiza tarifas_data en memoria.
    Devuelve True si hubo cambios (o force=True).
    """
    import importlib
    modulo_nombre = SCRAPERS.get(dist_id)
    if not modulo_nombre:
        logger.error(f"No hay scraper para '{dist_id}'")
        return False

    logger.info(f"=== Actualizando {dist_id.upper()} ===")
    try:
        modulo = importlib.import_module(modulo_nombre)
        nuevas_tarifas = modulo.scrape()
    except Exception as e:
        logger.error(f"{dist_id}: scraper falló — {e}")
        return False

    if not nuevas_tarifas:
        logger.warning(f"{dist_id}: scraper no devolvió datos (¿PDF no disponible?)")
        return False

    dist_data = tarifas_data.get(dist_id, {})
    tarifas_actuales = dist_data.get("tarifas", {})

    cambios = _diff_tarifas(tarifas_actuales, nuevas_tarifas)
    if not cambios and not force:
        logger.info(f"{dist_id}: sin cambios detectados")
        return False

    if cambios:
        logger.info(f"{dist_id}: {len(cambios)} cambio(s) detectado(s):")
        for c in cambios:
            logger.info(c)
    else:
        logger.info(f"{dist_id}: forzando actualización (--force)")

    if dry_run:
        logger.info(f"{dist_id}: modo dry-run, no se guarda")
        return True

    # Preservar campos de metadata de las tarifas que no extrae el scraper
    for tipo_tarifa, nueva in nuevas_tarifas.items():
        existente = tarifas_actuales.get(tipo_tarifa, {})
        # Mantener campos descriptivos que el scraper no modifica
        for campo_meta in ("nombre", "descripcion", "nota", "tipo_cargo_potencia"):
            if campo_meta in existente and campo_meta not in nueva:
                nueva[campo_meta] = existente[campo_meta]
        tarifas_data[dist_id]["tarifas"][tipo_tarifa].update(nueva)

    tarifas_data[dist_id]["ultima_actualizacion"] = date.today().isoformat()
    tarifas_data[dist_id]["datos_verificados"]    = True
    logger.info(f"{dist_id}: actualizado al {date.today()}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Actualizar tarifas eléctricas desde PDFs oficiales")
    parser.add_argument(
        "--dist", choices=list(SCRAPERS.keys()), default=None,
        help="Actualizar solo esta distribuidora (por defecto: todas)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Mostrar cambios sin guardar")
    parser.add_argument("--force",   action="store_true", help="Actualizar aunque no haya cambios")
    args = parser.parse_args()

    logger.info(f"Inicio actualización tarifas — {date.today()}")
    if args.dry_run:
        logger.info("MODO DRY-RUN: no se escribirá ningún archivo")

    tarifas_data  = _cargar_tarifas()
    dists_a_correr = [args.dist] if args.dist else list(SCRAPERS.keys())
    hubo_cambios  = False

    for dist_id in dists_a_correr:
        if dist_id not in tarifas_data:
            logger.warning(f"'{dist_id}' no existe en tarifas.json, saltando")
            continue
        if actualizar_distribuidora(dist_id, tarifas_data, dry_run=args.dry_run, force=args.force):
            hubo_cambios = True

    if hubo_cambios and not args.dry_run:
        _guardar_tarifas(tarifas_data)
        logger.info("Actualización completada con cambios guardados")
    elif not hubo_cambios:
        logger.info("Finalizado sin cambios")
    else:
        logger.info("Finalizado (dry-run, no se guardó nada)")


if __name__ == "__main__":
    main()
