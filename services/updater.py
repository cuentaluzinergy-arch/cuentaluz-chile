"""
services/updater.py — Orquestador de actualizacion de tarifas.

Flujo:
  1. Corre todos los scrapers en paralelo (ThreadPoolExecutor)
  2. Valida los resultados (no cero, no >50% de diferencia)
  3. Si hay cambios validos:
       a. Archiva tarifas actuales en data/tarifas_historico.json
       b. Actualiza config/tarifas.json
       c. Registra en data/logs/actualizaciones.log
       d. Envia alerta por email (si ALERT_EMAIL esta configurado)
  4. Si un scraper falla: mantiene datos anteriores, registra error, no interrumpe los demas

Uso manual:
    python -m services.updater               # todas las distribuidoras
    python -m services.updater --dist enel   # solo Enel
    python -m services.updater --dry-run     # muestra cambios sin guardar
    python -m services.updater --force       # actualiza aunque no haya cambios

Scheduling automatico (via main.py):
    Configurar ENABLE_SCHEDULER=true y TARIFF_UPDATE_DAY=1 en .env
"""
import argparse
import json
import logging
import os
import smtplib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Carga .env si existe
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_ROOT         = Path(__file__).resolve().parent.parent
_TARIFAS_PATH = _ROOT / "config" / "tarifas.json"
_HISTORICO    = _ROOT / "data" / "tarifas_historico.json"
_LOG_PATH     = _ROOT / "data" / "logs" / "actualizaciones.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger("updater")

# ── Scrapers disponibles ──────────────────────────────────────────────────────
def _get_scrapers() -> dict:
    from scrapers.enel_scraper       import EnelScraper
    from scrapers.cge_scraper        import CGEScraper
    from scrapers.chilquinta_scraper import ChilquintaScraper
    from scrapers.frontel_scraper    import FrontelScraper
    return {
        "enel":       EnelScraper(),
        "cge":        CGEScraper(),
        "chilquinta": ChilquintaScraper(),
        "frontel":    FrontelScraper(),
    }


# ── I/O ──────────────────────────────────────────────────────────────────────

def _cargar_tarifas() -> dict:
    with open(_TARIFAS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _guardar_tarifas(data: dict) -> None:
    with open(_TARIFAS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _archivar_historico(dist_id: str, tarifas_anteriores: dict) -> None:
    """Guarda una snapshot de las tarifas anteriores en tarifas_historico.json."""
    historico = json.loads(_HISTORICO.read_text(encoding="utf-8"))
    historico.append({
        "distribuidora_id":  dist_id,
        "archivado_en":      datetime.now().isoformat(timespec="seconds"),
        "tarifas":           tarifas_anteriores,
    })
    # Mantener solo los ultimos 100 registros por distribuidora para no crecer infinitamente
    historico = historico[-400:]
    _HISTORICO.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Email ─────────────────────────────────────────────────────────────────────

def _enviar_email(asunto: str, cuerpo: str) -> None:
    alert_email = os.getenv("ALERT_EMAIL")
    smtp_host   = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port   = int(os.getenv("SMTP_PORT", "587"))
    smtp_user   = os.getenv("SMTP_USER")
    smtp_pass   = os.getenv("SMTP_PASS")

    if not all([alert_email, smtp_user, smtp_pass]):
        logger.debug("Email no configurado (ALERT_EMAIL/SMTP_USER/SMTP_PASS). Saltando envio.")
        return

    try:
        msg = MIMEMultipart()
        msg["From"]    = smtp_user
        msg["To"]      = alert_email
        msg["Subject"] = f"[CuentaLuz] {asunto}"
        msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, alert_email, msg.as_string())
        logger.info(f"Email enviado a {alert_email}: {asunto}")
    except Exception as e:
        logger.error(f"Error enviando email: {e}")


# ── Logica principal ──────────────────────────────────────────────────────────

def _correr_scraper_individual(scraper) -> tuple[str, dict | None]:
    """Wrapper para ThreadPoolExecutor — devuelve (dist_id, resultado|None)."""
    try:
        resultado = scraper.scrape()
        return scraper.DISTRIBUIDORA_ID, resultado
    except Exception as e:
        logger.error(f"{scraper.DISTRIBUIDORA_ID}: scraper lanzo excepcion — {e}")
        return scraper.DISTRIBUIDORA_ID, None


def correr_scrapers(dists: list[str]) -> dict[str, dict | None]:
    """Corre los scrapers en paralelo. Devuelve {dist_id: resultado}."""
    todos = _get_scrapers()
    scrapers = [todos[d] for d in dists if d in todos]

    resultados = {}
    with ThreadPoolExecutor(max_workers=min(len(scrapers), 4)) as executor:
        futures = {executor.submit(_correr_scraper_individual, s): s.DISTRIBUIDORA_ID
                   for s in scrapers}
        for future in as_completed(futures):
            dist_id, resultado = future.result()
            resultados[dist_id] = resultado
            estado = "OK" if resultado else "FALLO"
            logger.info(f"{dist_id}: {estado}")

    return resultados


def aplicar_actualizacion(
    dist_id: str,
    nuevas_tarifas: dict,
    tarifas_data: dict,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[bool, list[str]]:
    """
    Valida y aplica las nuevas tarifas de una distribuidora.
    Devuelve (hubo_cambios, lista_de_cambios).
    """
    from scrapers.base_scraper import BaseScraper
    validator = BaseScraper()
    validator.DISTRIBUIDORA_ID = dist_id

    dist_data        = tarifas_data.get(dist_id, {})
    tarifas_actuales = dist_data.get("tarifas", {})

    # Validacion de integridad (no cero, no >50% diferencia)
    if not validator.validar_tarifas(nuevas_tarifas, tarifas_actuales):
        logger.error(f"{dist_id}: tarifas rechazadas por validacion. Se mantienen datos anteriores.")
        return False, []

    # Deteccion de cambios
    hay_cambios = force or validator.detectar_cambios(nuevas_tarifas, tarifas_actuales)
    if not hay_cambios:
        return False, []

    # Describir cambios para log y email
    cambios = []
    for tipo in ("BT1", "BT2"):
        nva = nuevas_tarifas.get(tipo, {})
        act = tarifas_actuales.get(tipo, {})
        for campo in ["cargo_fijo_neto", "cargo_energia_kwh_neto", "cargo_potencia_kwh_neto",
                      "cargo_transporte_kwh_neto", "cargo_demanda_punta_kw_mes_neto"]:
            v_nva = nva.get(campo)
            v_act = act.get(campo)
            if v_nva and v_act and abs(v_nva - v_act) > 0.1:
                cambios.append(f"  {tipo}.{campo}: {v_act} → {v_nva}")

    if dry_run:
        logger.info(f"{dist_id}: [DRY-RUN] {len(cambios)} cambio(s) — no se guarda")
        return True, cambios

    # Archivar version anterior
    _archivar_historico(dist_id, tarifas_actuales)

    # Aplicar nuevas tarifas (preservando campos descriptivos)
    for tipo, nueva in nuevas_tarifas.items():
        existente = tarifas_actuales.get(tipo, {})
        for meta_campo in ("nombre", "descripcion", "nota", "tipo_cargo_potencia"):
            if meta_campo in existente and meta_campo not in nueva:
                nueva[meta_campo] = existente[meta_campo]
        if tipo not in tarifas_data[dist_id]["tarifas"]:
            tarifas_data[dist_id]["tarifas"][tipo] = {}
        tarifas_data[dist_id]["tarifas"][tipo].update(nueva)

    tarifas_data[dist_id]["ultima_actualizacion"] = date.today().isoformat()
    tarifas_data[dist_id]["datos_verificados"]    = True

    return True, cambios


def run_update(dists: list[str] | None = None, dry_run: bool = False, force: bool = False) -> None:
    """
    Punto de entrada principal — llamado por CLI y por el scheduler.
    """
    if dists is None:
        dists = list(_get_scrapers().keys())

    logger.info(f"=== Inicio actualizacion tarifas {date.today()} ===")
    if dry_run:
        logger.info("MODO DRY-RUN: no se escribira ningun archivo")

    tarifas_data = _cargar_tarifas()
    resultados   = correr_scrapers(dists)

    cambios_totales = []
    dists_actualizadas = []

    for dist_id, nuevas_tarifas in resultados.items():
        if nuevas_tarifas is None:
            logger.warning(f"{dist_id}: sin datos del scraper, se mantienen tarifas anteriores")
            continue

        hubo, cambios = aplicar_actualizacion(
            dist_id, nuevas_tarifas, tarifas_data, dry_run=dry_run, force=force
        )
        if hubo:
            dists_actualizadas.append(dist_id)
            cambios_totales.extend([f"\n[{dist_id.upper()}]"] + cambios)

    if dists_actualizadas and not dry_run:
        # Actualizar metadata global
        tarifas_data.setdefault("metadata", {})["ultima_actualizacion"] = date.today().isoformat()
        _guardar_tarifas(tarifas_data)
        logger.info(f"tarifas.json actualizado. Distribuidoras: {', '.join(dists_actualizadas)}")

        if cambios_totales:
            # 1. Alerta interna al administrador
            cuerpo = (
                f"Actualizacion de tarifas — {date.today()}\n"
                f"Distribuidoras actualizadas: {', '.join(dists_actualizadas)}\n"
                f"\nCambios detectados:\n" + "\n".join(cambios_totales)
            )
            _enviar_email(
                f"Tarifas actualizadas — {', '.join(dists_actualizadas)}",
                cuerpo
            )

            # 2. Notificar a suscriptores email
            try:
                from database import SessionLocal
                from app.models.subscriber import Subscriber
                from services.email_service import send_tariff_update
                db = SessionLocal()
                try:
                    emails = [
                        r.email for r in
                        db.query(Subscriber.email)
                        .filter(Subscriber.activo == True)  # noqa: E712
                        .all()
                    ]
                finally:
                    db.close()
                if emails:
                    send_tariff_update(emails, dists_actualizadas, cambios_totales)
                    logger.info(f"Email enviado a {len(emails)} suscriptores")
            except Exception as e:
                logger.error(f"Error notificando suscriptores email: {e}")

            # 3. Notificar via Web Push
            try:
                from services.push_service import notify_tariff_update as push_notify
                enviados = push_notify(dists_actualizadas)
                logger.info(f"Push enviado a {enviados} dispositivos")
            except Exception as e:
                logger.error(f"Error notificando push: {e}")
    elif not dists_actualizadas:
        logger.info("Sin cambios detectados. tarifas.json no modificado.")

    logger.info("=== Fin actualizacion ===\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Actualizar tarifas electricas desde PDFs oficiales")
    parser.add_argument("--dist", choices=["enel", "cge", "chilquinta", "frontel"], default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force",   action="store_true", help="Actualizar aunque no haya cambios")
    args = parser.parse_args()

    dists = [args.dist] if args.dist else None
    run_update(dists=dists, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
