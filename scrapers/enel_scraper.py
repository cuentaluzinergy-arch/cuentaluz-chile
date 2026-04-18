"""
scrapers/enel_scraper.py — Scraper Enel Distribución Chile S.A.

Estructura PDF (Decreto 24T/2025 + VAD 5T/2024, vigente 01-04-2026):
  col 3 = descripcion | col 5 = $ Neto (primera comuna, uniforme en toda la RM)

Filas clave:
  "Cargo fijo mensual"                → cargo_fijo_neto
  "Cargo por servicio publico..."     → cargo_servicio_publico_kwh  (exento IVA)
  "Transporte de electricidad (2)"    → cargo_transporte_kwh_neto   (troncal+zonal)
  "Cargo por energia"                 → cargo_energia_kwh_neto
  "Cargo por compras de potencia"     → cargo_potencia_kwh_neto
"""
from pathlib import Path
from typing import Optional
import logging

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_FET_RECARGOS_DEFAULT = [
    {"desde_kwh": 0,    "hasta_kwh": 350,   "recargo_kwh": 0.000},
    {"desde_kwh": 350,  "hasta_kwh": 500,   "recargo_kwh": 0.923},
    {"desde_kwh": 500,  "hasta_kwh": 1000,  "recargo_kwh": 2.883},
    {"desde_kwh": 1000, "hasta_kwh": 5000,  "recargo_kwh": 3.229},
    {"desde_kwh": 5000, "hasta_kwh": 99999, "recargo_kwh": 3.229},
]


class EnelScraper(BaseScraper):
    DISTRIBUIDORA_ID = "enel"
    PDF_URL_BASE     = "https://www.eneldistribucion.cl/clientes/informacion-de-interes/tarifas"
    PDF_PATRON       = r"decreto.*24T|VAD.*5T|tarifa.*suministro|suministro.*electrico"

    def obtener_pdf(self) -> Optional[Path]:
        """Prioriza cualquier PDF de Enel en la raiz del proyecto."""
        raiz = Path(__file__).resolve().parent.parent
        for patron in ("Enel*.pdf", "enel*.pdf"):
            pdf = next(raiz.glob(patron), None)
            if pdf:
                logger.info(f"enel: usando PDF local: {pdf.name}")
                return pdf
        url = self.buscar_pdf_url()
        return self.descargar_pdf(url) if url else None

    def extraer_valores(self, filas: list) -> Optional[dict]:
        b = self.buscar_en_filas  # shorthand

        cargo_fijo  = b(filas, ["cargo fijo mensual", "cargo fijo"])
        serv_pub    = b(filas, ["cargo por servicio publico", "cargo por servicio público",
                                "servicio publico", "servicio público"])
        transporte  = b(filas, ["transporte de electricidad"])
        energia     = b(filas, ["cargo por energia", "cargo por energía"])
        potencia    = b(filas, ["cargo por compras de potencia", "compras de potencia"])
        demanda_punta = b(filas, ["demanda punta", "potencia punta", "cargo punta"])

        if not self.validar_extracion(cargo_fijo, serv_pub, energia):
            return None

        # FET recargos: usar defaults del decreto vigente
        # (la tabla de FET en el PDF usa formato muy variable; los valores son fijos por ley)
        bt1 = {
            "nombre":                    "BT1 - Residencial Normal",
            "cargo_fijo_neto":           cargo_fijo,
            "cargo_servicio_publico_kwh": serv_pub,
            "cargo_transporte_kwh_neto": transporte or 13.415,
            "cargo_energia_kwh_neto":    energia,
            "cargo_potencia_kwh_neto":   potencia or 26.029,
            "fet_recargos":              _FET_RECARGOS_DEFAULT,
        }

        resultado = {"BT1": bt1}

        if demanda_punta:
            resultado["BT2"] = {
                "nombre":                          "BT2 - Con Medidor Horario (demanda contratada)",
                "cargo_fijo_neto":                 cargo_fijo,
                "cargo_servicio_publico_kwh":      serv_pub,
                "cargo_transporte_kwh_neto":       transporte or 13.415,
                "cargo_energia_kwh_neto":          energia,
                "cargo_demanda_punta_kw_mes_neto": demanda_punta,
                "tipo_cargo_potencia":             "demanda",
            }

        logger.info(f"enel: fijo={cargo_fijo}, energia={energia}, transporte={transporte}, potencia={potencia}")
        return resultado

    def validar_extracion(self, fijo, serv_pub, energia) -> bool:
        if not all([fijo, serv_pub, energia]):
            logger.warning(f"enel: extraccion incompleta — fijo={fijo}, serv_pub={serv_pub}, energia={energia}")
            return False
        return True
