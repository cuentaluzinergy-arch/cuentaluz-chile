"""
Scraper de tarifas CGE Distribución S.A.

CGE publica sus decretos tarifarios en:
  https://www.cge.cl/informacion-clientes/tarifas/

Los PDFs siguen una estructura similar al de Enel (decreto CNE estándar),
pero con valores distintos según el área de concesión de CGE.

Estado: parser genérico CNE. Requiere validar contra el PDF oficial de CGE
una vez descargado (columnas pueden diferir según versión del decreto).
"""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PDF_URL_BASE = "https://www.cge.cl/informacion-clientes/tarifas/"
_PDF_PATRON   = r"decreto.*tarifa|tarifa.*bt|suministro.*electrico|bt1|bt2"


def _extraer_tabla_completa(pdf_path: Path) -> list:
    try:
        import pdfplumber
        filas = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for tabla in page.extract_tables():
                    filas.extend(tabla)
        return filas
    except Exception as e:
        logger.error(f"Error extrayendo tablas: {e}")
        return []


def parsear_pdf(path_pdf: Path) -> Optional[dict]:
    """
    Extrae valores tarifarios BT1 y BT2 de un PDF de CGE.
    Usa el mismo patrón de columnas ($ neto / $ IVA) que Enel.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber no instalado. Ejecuta: pip install pdfplumber")
        return None

    from scraper.base_scraper import normalizar_numero
    filas = _extraer_tabla_completa(path_pdf)

    if not filas:
        logger.warning(f"No se encontraron tablas en {path_pdf.name}")
        return None

    logger.info(f"CGE: {len(filas)} filas extraídas del PDF")
    for i, fila in enumerate(filas[:30]):
        logger.debug(f"  [{i:02d}] {fila}")

    # Buscar valores con palabras clave estándar CNE
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

    cargo_fijo    = buscar(["cargo fijo", "cargo mensual"])
    serv_pub      = buscar(["servicio público", "servicio publico", "cargo público"])
    troncal       = buscar(["troncal"])
    zonal         = buscar(["zonal"])
    transporte    = round(troncal + zonal, 6) if troncal and zonal else buscar(["transporte", "transmisión"])
    energia       = buscar(["precio nudo", "cargo energía", "cargo energia", "nudo"])
    potencia      = buscar(["vad", "potencia", "valor agregado"])
    demanda_punta = buscar(["demanda punta", "cargo punta", "potencia punta"])

    if not all([cargo_fijo, serv_pub, energia]):
        logger.warning(
            f"CGE: valores insuficientes extraídos. "
            f"fijo={cargo_fijo}, serv_pub={serv_pub}, energia={energia}\n"
            f"Verifica el formato del PDF en {path_pdf}"
        )
        return None

    fet_recargos = [
        {"desde_kwh": 0,    "hasta_kwh": 350,   "recargo_kwh": 0.000},
        {"desde_kwh": 350,  "hasta_kwh": 500,   "recargo_kwh": 0.923},
        {"desde_kwh": 500,  "hasta_kwh": 1000,  "recargo_kwh": 2.883},
        {"desde_kwh": 1000, "hasta_kwh": 99999, "recargo_kwh": 3.229},
    ]

    resultado = {
        "BT1": {
            "cargo_fijo_neto":            cargo_fijo,
            "cargo_servicio_publico_kwh": serv_pub,
            "cargo_transporte_kwh_neto":  transporte or 14.2,
            "cargo_energia_kwh_neto":     energia,
            "cargo_potencia_kwh_neto":    potencia or 24.0,
            "fet_recargos":               fet_recargos,
        }
    }
    if demanda_punta:
        resultado["BT2"] = {
            "cargo_fijo_neto":                 cargo_fijo,
            "cargo_servicio_publico_kwh":      serv_pub,
            "cargo_transporte_kwh_neto":       transporte or 14.2,
            "cargo_energia_kwh_neto":          energia,
            "cargo_demanda_punta_kw_mes_neto": demanda_punta,
            "tipo_cargo_potencia":             "demanda",
        }

    logger.info(f"CGE: extracción exitosa → fijo={cargo_fijo}, energía={energia}")
    return resultado


def obtener_pdf() -> Optional[Path]:
    from scraper.base_scraper import buscar_pdf_en_pagina, descargar_pdf
    logger.info("Buscando PDF de CGE en su sitio web...")
    url_pdf = buscar_pdf_en_pagina(_PDF_URL_BASE, _PDF_PATRON)
    if url_pdf:
        return descargar_pdf(url_pdf, "cge_tarifas_vigente.pdf")
    logger.error("No se encontró PDF de CGE en el sitio web")
    return None


def scrape() -> Optional[dict]:
    pdf_path = obtener_pdf()
    if not pdf_path:
        return None
    return parsear_pdf(pdf_path)
