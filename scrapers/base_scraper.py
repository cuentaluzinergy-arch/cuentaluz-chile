"""
scrapers/base_scraper.py — Clase base para todos los scrapers de distribuidoras.

Responsabilidades:
  - fetch_url:        GET con retry exponencial (3 intentos)
  - parse_pdf:        Extrae todas las filas de tablas del PDF con pdfplumber
  - detectar_cambios: Compara dos dicts de tarifas → bool
  - validar_tarifas:  Rechaza valores cero, negativos o >50% distintos al actual
  - buscar_pdf_url:   Busca el link al PDF más reciente en una página HTML
  - scrape:           Orquestador — implementado por cada subclase
"""
import logging
import re
import time
from pathlib import Path
from typing import Optional
import unicodedata

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "pdfs"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Campos que se comparan para detectar cambios tarifarios reales
_CAMPOS_COMPARAR = [
    "cargo_fijo_neto",
    "cargo_servicio_publico_kwh",
    "cargo_transporte_kwh_neto",
    "cargo_energia_kwh_neto",
    "cargo_potencia_kwh_neto",
    "cargo_demanda_punta_kw_mes_neto",
]

# Variacion maxima aceptada antes de rechazar (50%)
_MAX_VARIACION = 0.50
# Diferencia minima para considerar un cambio real (evita falsos positivos por redondeo)
_UMBRAL_CAMBIO = 0.5


class BaseScraper:
    """Clase base. Cada distribuidora hereda y sobreescribe DISTRIBUIDORA_ID, PDF_URL_BASE, PDF_PATRON."""

    DISTRIBUIDORA_ID: str = ""
    PDF_URL_BASE: str = ""
    PDF_PATRON: str = r"tarifa|decreto|bt1|bt2|suministro"

    def __init__(self):
        import requests
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    # ── Red ─────────────────────────────────────────────────────────────────

    def fetch_url(self, url: str, timeout: int = 30, max_retries: int = 3):
        """GET con retry exponencial. Lanza la ultima excepcion si todos fallan."""
        ultimo_error = None
        for intento in range(max_retries):
            try:
                r = self.session.get(url, timeout=timeout)
                r.raise_for_status()
                return r
            except Exception as e:
                ultimo_error = e
                if intento < max_retries - 1:
                    wait = 2 ** intento      # 1s, 2s, 4s
                    logger.warning(f"{self.DISTRIBUIDORA_ID}: intento {intento+1} fallido ({e}). Reintentando en {wait}s")
                    time.sleep(wait)
        raise ultimo_error  # type: ignore[misc]

    def buscar_pdf_url(self) -> Optional[str]:
        """Busca el link al PDF mas reciente en PDF_URL_BASE usando PDF_PATRON."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
            r = self.fetch_url(self.PDF_URL_BASE)
            soup = BeautifulSoup(r.text, "html.parser")
            patron = re.compile(self.PDF_PATRON, re.IGNORECASE)
            for a in soup.find_all("a", href=True):
                href = str(a["href"])
                texto = a.get_text(strip=True)
                if patron.search(href) or patron.search(texto):
                    url = href if href.startswith("http") else urljoin(self.PDF_URL_BASE, href)
                    logger.info(f"{self.DISTRIBUIDORA_ID}: PDF encontrado → {url}")
                    return url
            logger.warning(f"{self.DISTRIBUIDORA_ID}: no se encontro PDF con patron '{self.PDF_PATRON}' en {self.PDF_URL_BASE}")
            return None
        except Exception as e:
            logger.error(f"{self.DISTRIBUIDORA_ID}: error buscando PDF en pagina — {e}")
            return None

    def descargar_pdf(self, url: str) -> Optional[Path]:
        """Descarga el PDF y lo guarda en cache/pdfs/."""
        nombre = f"{self.DISTRIBUIDORA_ID}_vigente.pdf"
        destino = _CACHE_DIR / nombre
        try:
            r = self.fetch_url(url, timeout=60)
            destino.write_bytes(r.content)
            logger.info(f"{self.DISTRIBUIDORA_ID}: PDF descargado ({len(r.content)/1024:.1f} KB) → {destino}")
            return destino
        except Exception as e:
            logger.error(f"{self.DISTRIBUIDORA_ID}: error descargando PDF — {e}")
            return None

    # ── PDF ─────────────────────────────────────────────────────────────────

    def parse_pdf(self, filepath: Path) -> list:
        """Extrae todas las filas de tablas del PDF. Devuelve lista plana de filas."""
        try:
            import pdfplumber
            filas = []
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    for tabla in page.extract_tables():
                        filas.extend(tabla)
            logger.debug(f"{self.DISTRIBUIDORA_ID}: {len(filas)} filas extraidas del PDF")
            return filas
        except Exception as e:
            logger.error(f"{self.DISTRIBUIDORA_ID}: error parseando PDF — {e}")
            return []

    @staticmethod
    def normalizar_numero(texto: str) -> Optional[float]:
        """
        Convierte string numerico chileno/europeo a float.
        '596,176' → 596.176 | '1.234,56' → 1234.56 | '131.039' → 131.039
        """
        if not texto:
            return None
        texto = str(texto).strip().replace(" ", "").replace("$", "")
        if "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif "," in texto:
            texto = texto.replace(",", ".")
        try:
            val = float(texto)
            return val if val >= 0 else None
        except ValueError:
            return None

    def buscar_en_filas(self, filas: list, palabras_clave: list[str],
                        col_desc: int = 3, col_neto: int = 5) -> Optional[float]:
        """Busca en col_desc la primera fila que contenga alguna clave y devuelve col_neto."""
        kw = [k.lower() for k in palabras_clave]
        for fila in filas:
            desc = str(fila[col_desc] if len(fila) > col_desc else "").lower()
            texto = " ".join(str(c or "") for c in fila).lower()
            if any(k in desc or k in texto for k in kw):
                try:
                    val = self.normalizar_numero(str(fila[col_neto] if len(fila) > col_neto else ""))
                    if val is not None and val > 0:
                        return val
                except (IndexError, TypeError):
                    pass
        return None

    # ── Validacion y cambios ─────────────────────────────────────────────────

    def detectar_cambios(self, nuevas: dict, actuales: dict) -> bool:
        """True si algun campo tarifario cambio mas de _UMBRAL_CAMBIO."""
        for tipo in ("BT1", "BT2"):
            nva = nuevas.get(tipo, {})
            act = actuales.get(tipo, {})
            if not nva:
                continue
            for campo in _CAMPOS_COMPARAR:
                v_nva = nva.get(campo)
                v_act = act.get(campo)
                if v_nva is not None and v_act is not None:
                    if abs(v_nva - v_act) > _UMBRAL_CAMBIO:
                        logger.info(f"Cambio detectado: {tipo}.{campo} {v_act} → {v_nva}")
                        return True
        return False

    def validar_tarifas(self, nuevas: dict, actuales: dict) -> bool:
        """
        Rechaza las nuevas tarifas si:
          - cargo_energia_kwh_neto es cero o negativo
          - cualquier campo critico difiere mas de 50% del valor actual
        """
        bt1_nva = nuevas.get("BT1", {})
        bt1_act = actuales.get("BT1", {})

        energia_nva = bt1_nva.get("cargo_energia_kwh_neto", 0)
        if energia_nva <= 0:
            logger.error(f"{self.DISTRIBUIDORA_ID}: energia={energia_nva} invalido (cero o negativo)")
            return False

        energia_act = bt1_act.get("cargo_energia_kwh_neto", energia_nva)
        if energia_act > 0:
            variacion = abs(energia_nva - energia_act) / energia_act
            if variacion > _MAX_VARIACION:
                logger.error(
                    f"{self.DISTRIBUIDORA_ID}: variacion de energia {variacion:.0%} supera el 50%. "
                    f"Actual={energia_act}, nuevo={energia_nva}. Se mantienen valores anteriores."
                )
                return False

        fijo_nva = bt1_nva.get("cargo_fijo_neto", 0)
        if fijo_nva <= 0:
            logger.error(f"{self.DISTRIBUIDORA_ID}: cargo_fijo={fijo_nva} invalido")
            return False

        return True

    # ── Punto de entrada ─────────────────────────────────────────────────────

    def obtener_pdf(self) -> Optional[Path]:
        """
        Estrategia: 1) PDF local en raiz del proyecto, 2) descarga web.
        Las subclases pueden sobreescribir para buscar en rutas distintas.
        """
        raiz = Path(__file__).resolve().parent.parent
        pdf_local = next(raiz.glob(f"{self.DISTRIBUIDORA_ID.capitalize()}*.pdf"), None)
        if pdf_local:
            logger.info(f"{self.DISTRIBUIDORA_ID}: usando PDF local: {pdf_local.name}")
            return pdf_local

        url = self.buscar_pdf_url()
        if url:
            return self.descargar_pdf(url)
        return None

    def extraer_valores(self, filas: list) -> Optional[dict]:
        """Extrae los valores tarifarios de las filas del PDF. Implementar en subclases."""
        raise NotImplementedError(f"{self.__class__.__name__} debe implementar extraer_valores()")

    def scrape(self) -> Optional[dict]:
        """
        Flujo completo: obtener PDF → parsear → extraer → devolver dict o None.
        Falla silenciosamente: devuelve None en cualquier error, sin lanzar excepciones.
        """
        try:
            pdf_path = self.obtener_pdf()
            if not pdf_path:
                logger.warning(f"{self.DISTRIBUIDORA_ID}: no se pudo obtener el PDF")
                return None
            filas = self.parse_pdf(pdf_path)
            if not filas:
                logger.warning(f"{self.DISTRIBUIDORA_ID}: PDF sin tablas extraibles")
                return None
            resultado = self.extraer_valores(filas)
            if resultado:
                logger.info(f"{self.DISTRIBUIDORA_ID}: scrape completado ({len(resultado)} tipos de tarifa)")
            return resultado
        except Exception as e:
            logger.exception(f"{self.DISTRIBUIDORA_ID}: error inesperado en scrape — {e}")
            return None
