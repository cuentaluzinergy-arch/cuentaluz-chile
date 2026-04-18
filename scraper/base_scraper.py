"""
Utilidades compartidas entre scrapers de distribuidoras.
"""
import logging
import re
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "pdfs"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def descargar_pdf(url: str, nombre_cache: str, timeout: int = 30) -> Optional[Path]:
    """
    Descarga un PDF a la carpeta cache/pdfs/.
    Devuelve el Path al archivo o None si falla.
    """
    destino = _CACHE_DIR / nombre_cache
    try:
        logger.info(f"Descargando {url} → {destino.name}")
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        if "pdf" not in r.headers.get("Content-Type", "").lower() and not url.lower().endswith(".pdf"):
            logger.warning(f"Respuesta no es PDF (Content-Type: {r.headers.get('Content-Type')})")
        destino.write_bytes(r.content)
        logger.info(f"PDF guardado: {destino} ({len(r.content)/1024:.1f} KB)")
        return destino
    except requests.RequestException as e:
        logger.error(f"Error descargando {url}: {e}")
        return None


def normalizar_numero(texto: str) -> Optional[float]:
    """
    Convierte un string de número chileno/europeo a float.
    Maneja formatos: '596,176' → 596.176 | '1.234,56' → 1234.56 | '131.039' → 131.039
    """
    if not texto:
        return None
    texto = texto.strip().replace(" ", "").replace("$", "")
    # Si tiene punto Y coma: el punto es miles y la coma es decimal → '1.234,56'
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    # Si solo tiene coma: puede ser decimal chileno '596,176'
    elif "," in texto:
        texto = texto.replace(",", ".")
    # Si solo tiene punto: puede ser miles '596.176' o decimal '131.039'
    # En tarifas CNE los valores netos están en rango 0-30000, así que
    # '596.176' → 596.176 (decimal), no 596176 (miles)
    try:
        return float(texto)
    except ValueError:
        return None


def buscar_pdf_en_pagina(url_pagina: str, patron_pdf: str) -> Optional[str]:
    """
    Busca un link a PDF en una página HTML usando una expresión regular.
    Devuelve la URL absoluta del PDF o None.
    """
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url_pagina, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        patron = re.compile(patron_pdf, re.IGNORECASE)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            texto = a.get_text(strip=True)
            if patron.search(href) or patron.search(texto):
                if href.startswith("http"):
                    return href
                # URL relativa → construir absoluta
                from urllib.parse import urljoin
                return urljoin(url_pagina, href)
        logger.warning(f"No se encontró PDF con patrón '{patron_pdf}' en {url_pagina}")
        return None
    except Exception as e:
        logger.error(f"Error buscando PDF en {url_pagina}: {e}")
        return None
