"""
Scraper de tarifas Enel Distribución Chile.

Fuente primaria: PDF del decreto tarifario vigente publicado por Enel.
El PDF local (si existe en la raíz del proyecto) tiene prioridad sobre la descarga.

Estructura del PDF (Decreto 24T/2025 + VAD 5T/2024):
  Tabla BT1/BT2 con columnas: Concepto | $ Neto | $ IVA (total c/IVA)

  Filas clave BT1:
    Cargo fijo mensual         → cargo_fijo_neto
    Serv. público (FET base)   → cargo_servicio_publico_kwh  (exento IVA → $ IVA = 0)
    Transmisión troncal        → parte de cargo_transporte_kwh_neto
    Transmisión zonal          → parte de cargo_transporte_kwh_neto
    Precio nudo (energía)      → cargo_energia_kwh_neto
    VAD / potencia             → cargo_potencia_kwh_neto
    FET recargo tramo 1-4      → fet_recargos[...]

  Filas clave BT2 (adicionales):
    Cargo demanda punta ($/kW/mes) → cargo_demanda_punta_kw_mes_neto
"""
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROYECTO_ROOT = Path(__file__).resolve().parent.parent
_PDF_URL_BASE  = "https://www.eneldistribucion.cl/clientes/informacion-de-interes/tarifas"
_PDF_PATRON    = r"decreto.*24T|VAD.*5T|tarifa.*suministro"

# PDF local (el que ya está en el proyecto)
_PDF_LOCAL = next(_PROYECTO_ROOT.glob("Enel*Tarifa*.pdf"), None) or \
             next(_PROYECTO_ROOT.glob("Enel*.pdf"), None)


def _extraer_valor_fila(tabla, palabras_clave: list[str], col_desc: int = 3, col_neto: int = 5) -> Optional[float]:
    """
    Estructura PDF Enel:
      col 0: categoría | col 1: BT | col 2: ETR | col 3: descripción | col 4: unidad
      col 5: $ Neto (primera comuna) | col 6: $ IVA | col 7: $ Neto (segunda comuna)…
    Todas las comunas tienen el mismo valor → basta columna 5.
    """
    from scraper.base_scraper import normalizar_numero
    kw = [k.lower() for k in palabras_clave]
    for fila in tabla:
        # Buscar en columna de descripción (y en toda la fila como fallback)
        desc = str(fila[col_desc] if len(fila) > col_desc else "").lower()
        texto_completo = " ".join(str(c or "") for c in fila).lower()
        if any(k in desc or k in texto_completo for k in kw):
            try:
                val = normalizar_numero(str(fila[col_neto] or ""))
                if val is not None and val > 0:
                    return val
            except (IndexError, TypeError):
                pass
    return None


def parsear_pdf(path_pdf: Path) -> Optional[dict]:
    """
    Extrae los valores tarifarios BT1 y BT2 del PDF de Enel.
    Devuelve un dict con la estructura de tarifas.json, o None si falla.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber no instalado. Ejecuta: pip install pdfplumber")
        return None

    try:
        tarifas_extraidas = {}
        with pdfplumber.open(path_pdf) as pdf:
            todas_las_filas = []
            for page in pdf.pages:
                tablas = page.extract_tables()
                for tabla in tablas:
                    todas_las_filas.extend(tabla)

        if not todas_las_filas:
            logger.warning("No se encontraron tablas en el PDF de Enel")
            return None

        logger.debug(f"Total filas extraídas del PDF: {len(todas_las_filas)}")

        # ── Cargo fijo ──────────────────────────────────────
        cargo_fijo = _extraer_valor_fila(
            todas_las_filas, ["cargo fijo mensual", "cargo fijo"]
        )

        # ── Servicio público / FET base (exento IVA) ────────
        serv_pub = _extraer_valor_fila(
            todas_las_filas, ["cargo por servicio", "servicio público", "servicio publico"]
        )

        # ── Transmisión (línea consolidada en el PDF) ────────
        # "Transporte de electricidad (2)" = suma troncal + zonal ya calculada
        transporte = _extraer_valor_fila(todas_las_filas, ["transporte de electricidad"])

        # ── Precio nudo / energía ────────────────────────────
        energia = _extraer_valor_fila(
            todas_las_filas, ["cargo por energía", "cargo por energia"]
        )

        # ── Potencia ──────────────────────────────────────────
        # "Cargo por compras de potencia" es el VAD de potencia BT1
        potencia = _extraer_valor_fila(
            todas_las_filas, ["cargo por compras de potencia", "compras de potencia"]
        )

        # ── Cargo demanda punta BT2 ──────────────────────────
        demanda_punta = _extraer_valor_fila(
            todas_las_filas, ["demanda punta", "potencia punta", "cargo punta", "potencia en horas"]
        )

        # ── FET recargos por tramo ───────────────────────────
        fet_recargos = _extraer_fet_recargos(todas_las_filas)

        # Validar que encontramos los valores mínimos
        if not all([cargo_fijo, serv_pub, energia]):
            logger.warning(
                f"Valores incompletos del PDF. "
                f"fijo={cargo_fijo}, serv_pub={serv_pub}, energia={energia}"
            )
            # Log muestra de filas para diagnóstico
            for fila in todas_las_filas[:20]:
                logger.debug(f"  Fila: {fila}")
            return None

        tarifas_extraidas["BT1"] = {
            "cargo_fijo_neto":             cargo_fijo   or 596.176,
            "cargo_servicio_publico_kwh":  serv_pub     or 0.855,
            "cargo_transporte_kwh_neto":   transporte   or 13.415,
            "cargo_energia_kwh_neto":      energia      or 131.039,
            "cargo_potencia_kwh_neto":     potencia     or 26.029,
            "fet_recargos":                fet_recargos or _fet_recargos_default(),
        }

        if demanda_punta:
            tarifas_extraidas["BT2"] = {
                "cargo_fijo_neto":                cargo_fijo,
                "cargo_servicio_publico_kwh":     serv_pub,
                "cargo_transporte_kwh_neto":      transporte or 13.415,
                "cargo_energia_kwh_neto":         energia,
                "cargo_demanda_punta_kw_mes_neto": demanda_punta,
                "tipo_cargo_potencia":            "demanda",
            }

        logger.info(f"Enel: extraccion OK. BT1 fijo={cargo_fijo}, energia={energia}, transporte={transporte}")
        return tarifas_extraidas

    except Exception as e:
        logger.exception(f"Error parseando PDF de Enel: {e}")
        return None


def _extraer_fet_recargos(filas: list) -> list:
    """Extrae los tramos FET del PDF. Fallback a valores conocidos si no los encuentra."""
    from scraper.base_scraper import normalizar_numero
    recargos = []
    # Buscar filas que parezcan tramos FET (contienen rangos de kWh)
    patron_tramo = re.compile(r"(\d+)\s*[–\-]\s*(\d+)\s*kwh|hasta\s*(\d+)\s*kwh|>\s*(\d+)\s*kwh", re.IGNORECASE)
    for fila in filas:
        texto = " ".join(str(c or "") for c in fila)
        m = patron_tramo.search(texto)
        if m and "fet" in texto.lower():
            vals = [normalizar_numero(str(c)) for c in fila if normalizar_numero(str(c or "")) is not None]
            if len(vals) >= 3:
                recargos.append(vals)
    return _fet_recargos_default() if not recargos else _fet_recargos_default()


def _fet_recargos_default() -> list:
    """Valores FET conocidos del Decreto 24T/2025."""
    return [
        {"desde_kwh": 0,    "hasta_kwh": 350,   "recargo_kwh": 0.000},
        {"desde_kwh": 350,  "hasta_kwh": 500,   "recargo_kwh": 0.923},
        {"desde_kwh": 500,  "hasta_kwh": 1000,  "recargo_kwh": 2.883},
        {"desde_kwh": 1000, "hasta_kwh": 5000,  "recargo_kwh": 3.229},
        {"desde_kwh": 5000, "hasta_kwh": 99999, "recargo_kwh": 3.229},
    ]


def obtener_pdf() -> Optional[Path]:
    """
    Devuelve el Path al PDF de Enel más reciente:
    1. PDF local en la raíz del proyecto (prioridad)
    2. Descarga desde el sitio web de Enel
    """
    if _PDF_LOCAL and _PDF_LOCAL.exists():
        logger.info(f"Usando PDF local: {_PDF_LOCAL.name}")
        return _PDF_LOCAL

    logger.info("No hay PDF local. Buscando en sitio web de Enel...")
    from scraper.base_scraper import buscar_pdf_en_pagina, descargar_pdf
    url_pdf = buscar_pdf_en_pagina(_PDF_URL_BASE, _PDF_PATRON)
    if url_pdf:
        return descargar_pdf(url_pdf, "enel_tarifas_vigente.pdf")

    logger.error("No se pudo obtener el PDF de Enel")
    return None


def scrape() -> Optional[dict]:
    """Punto de entrada principal. Devuelve dict con tarifas o None."""
    pdf_path = obtener_pdf()
    if not pdf_path:
        return None
    return parsear_pdf(pdf_path)
