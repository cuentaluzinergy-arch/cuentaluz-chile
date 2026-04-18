"""
scrapers/cge_scraper.py — Scraper CGE Distribucion S.A.
Fuente: https://www.cge.cl/informacion-clientes/tarifas/
"""
import logging
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_FET = [
    {"desde_kwh": 0,    "hasta_kwh": 350,   "recargo_kwh": 0.000},
    {"desde_kwh": 350,  "hasta_kwh": 500,   "recargo_kwh": 0.923},
    {"desde_kwh": 500,  "hasta_kwh": 1000,  "recargo_kwh": 2.883},
    {"desde_kwh": 1000, "hasta_kwh": 99999, "recargo_kwh": 3.229},
]


class CGEScraper(BaseScraper):
    DISTRIBUIDORA_ID = "cge"
    PDF_URL_BASE     = "https://www.cge.cl/informacion-clientes/tarifas/"
    PDF_PATRON       = r"tarifa.*bt|bt1|bt2|decreto.*tarifa|suministro.*electrico"

    def extraer_valores(self, filas: list):
        b = self.buscar_en_filas
        cargo_fijo = b(filas, ["cargo fijo mensual", "cargo fijo"])
        serv_pub   = b(filas, ["servicio publico", "servicio público", "cargo publico"])
        troncal    = b(filas, ["troncal"])
        zonal      = b(filas, ["zonal"])
        transporte = round(troncal + zonal, 6) if (troncal and zonal) else \
                     b(filas, ["transporte de electricidad", "transporte", "transmision"])
        energia    = b(filas, ["cargo por energia", "cargo por energía", "precio nudo", "nudo"])
        potencia   = b(filas, ["cargo por compras de potencia", "compras de potencia", "vad", "potencia"])
        demanda    = b(filas, ["demanda punta", "cargo punta"])

        if not all([cargo_fijo, serv_pub, energia]):
            logger.warning(f"cge: extraccion incompleta — fijo={cargo_fijo}, serv_pub={serv_pub}, energia={energia}")
            return None

        resultado = {
            "BT1": {
                "nombre":                    "BT1 - Residencial Normal",
                "cargo_fijo_neto":           cargo_fijo,
                "cargo_servicio_publico_kwh": serv_pub,
                "cargo_transporte_kwh_neto": transporte or 14.2,
                "cargo_energia_kwh_neto":    energia,
                "cargo_potencia_kwh_neto":   potencia or 24.0,
                "fet_recargos":              _FET,
            }
        }
        if demanda:
            resultado["BT2"] = {
                "nombre":                          "BT2 - Con Medidor Horario (demanda contratada)",
                "cargo_fijo_neto":                 cargo_fijo,
                "cargo_servicio_publico_kwh":      serv_pub,
                "cargo_transporte_kwh_neto":       transporte or 14.2,
                "cargo_energia_kwh_neto":          energia,
                "cargo_demanda_punta_kw_mes_neto": demanda,
                "tipo_cargo_potencia":             "demanda",
            }

        logger.info(f"cge: fijo={cargo_fijo}, energia={energia}")
        return resultado
