"""
Scraper de tarifas Chilquinta Energía S.A. (V Región de Valparaíso).
Fuente: https://www.chilquinta.cl/clientes/tarifas/
"""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PDF_URL_BASE = "https://www.chilquinta.cl/clientes/tarifas/"
_PDF_PATRON   = r"tarifa|decreto|bt1|bt2|suministro"


def parsear_pdf(path_pdf: Path) -> Optional[dict]:
    """Mismo parser genérico CNE que CGE."""
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber no instalado.")
        return None

    from scraper.base_scraper import normalizar_numero
    filas = []
    with pdfplumber.open(path_pdf) as pdf:
        for page in pdf.pages:
            for tabla in page.extract_tables():
                filas.extend(tabla)

    if not filas:
        logger.warning(f"No se encontraron tablas en {path_pdf.name}")
        return None

    def buscar(palabras, col=1):
        kw = [k.lower() for k in palabras]
        for fila in filas:
            texto = " ".join(str(c or "") for c in fila).lower()
            if any(k in texto for k in kw):
                try:
                    val = normalizar_numero(str(fila[col] or ""))
                    if val and val > 0:
                        return val
                except (IndexError, TypeError):
                    pass
        return None

    cargo_fijo  = buscar(["cargo fijo", "cargo mensual"])
    serv_pub    = buscar(["servicio público", "servicio publico", "cargo público"])
    troncal     = buscar(["troncal"])
    zonal       = buscar(["zonal"])
    transporte  = round(troncal + zonal, 6) if troncal and zonal else buscar(["transporte", "transmisión"])
    energia     = buscar(["precio nudo", "cargo energía", "cargo energia", "nudo"])
    potencia    = buscar(["vad", "potencia"])
    demanda     = buscar(["demanda punta", "cargo punta"])

    if not all([cargo_fijo, serv_pub, energia]):
        logger.warning(f"Chilquinta: valores insuficientes. fijo={cargo_fijo}, energia={energia}")
        return None

    fet = [
        {"desde_kwh": 0,    "hasta_kwh": 350,   "recargo_kwh": 0.000},
        {"desde_kwh": 350,  "hasta_kwh": 500,   "recargo_kwh": 0.923},
        {"desde_kwh": 500,  "hasta_kwh": 1000,  "recargo_kwh": 2.883},
        {"desde_kwh": 1000, "hasta_kwh": 99999, "recargo_kwh": 3.229},
    ]

    resultado = {
        "BT1": {
            "cargo_fijo_neto":            cargo_fijo,
            "cargo_servicio_publico_kwh": serv_pub,
            "cargo_transporte_kwh_neto":  transporte or 15.1,
            "cargo_energia_kwh_neto":     energia,
            "cargo_potencia_kwh_neto":    potencia or 25.5,
            "fet_recargos":               fet,
        }
    }
    if demanda:
        resultado["BT2"] = {
            "cargo_fijo_neto":                 cargo_fijo,
            "cargo_servicio_publico_kwh":      serv_pub,
            "cargo_transporte_kwh_neto":       transporte or 15.1,
            "cargo_energia_kwh_neto":          energia,
            "cargo_demanda_punta_kw_mes_neto": demanda,
            "tipo_cargo_potencia":             "demanda",
        }

    logger.info(f"Chilquinta: extracción exitosa → fijo={cargo_fijo}, energía={energia}")
    return resultado


def obtener_pdf() -> Optional[Path]:
    from scraper.base_scraper import buscar_pdf_en_pagina, descargar_pdf
    url_pdf = buscar_pdf_en_pagina(_PDF_URL_BASE, _PDF_PATRON)
    if url_pdf:
        return descargar_pdf(url_pdf, "chilquinta_tarifas_vigente.pdf")
    logger.error("No se encontró PDF de Chilquinta")
    return None


def scrape() -> Optional[dict]:
    pdf_path = obtener_pdf()
    if not pdf_path:
        return None
    return parsear_pdf(pdf_path)
