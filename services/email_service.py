"""
Servicio de email compartido — newsletter, bienvenida y alertas de tarifas.
Variables de entorno requeridas: SMTP_USER, SMTP_PASS
Opcionales: SMTP_HOST (gmail por defecto), SMTP_PORT (587), FROM_EMAIL, BASE_URL.
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("BASE_URL", "https://cuentaluz.cl")


def _cfg() -> dict | None:
    user  = os.getenv("SMTP_USER")
    passw = os.getenv("SMTP_PASS")
    if not (user and passw):
        return None
    return {
        "host":  os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port":  int(os.getenv("SMTP_PORT", "587")),
        "user":  user,
        "pass":  passw,
        "from":  os.getenv("FROM_EMAIL", user),
    }


def send(to: str | list[str], subject: str, body_html: str, body_text: str = "") -> bool:
    cfg = _cfg()
    if not cfg:
        logger.debug("SMTP no configurado — email omitido")
        return False

    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        return False

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            server.starttls()
            server.login(cfg["user"], cfg["pass"])
            for recipient in recipients:
                msg = MIMEMultipart("alternative")
                msg["From"]    = cfg["from"]
                msg["To"]      = recipient
                msg["Subject"] = subject
                if body_text:
                    msg.attach(MIMEText(body_text, "plain", "utf-8"))
                msg.attach(MIMEText(body_html, "html", "utf-8"))
                server.sendmail(cfg["from"], recipient, msg.as_string())
        logger.info(f"Email enviado a {len(recipients)} destinatario(s): {subject}")
        return True
    except Exception as e:
        logger.error(f"Error enviando email: {e}")
        return False


def send_welcome(email: str, unsubscribe_token: str) -> bool:
    url_baja = f"{BASE_URL}/newsletter/baja?token={unsubscribe_token}"
    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:system-ui,sans-serif;background:#f8fafc;margin:0;padding:20px">
<div style="max-width:560px;margin:auto;background:white;border-radius:16px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
  <div style="background:linear-gradient(135deg,#1d4ed8,#3b82f6);padding:32px;text-align:center">
    <div style="display:inline-block;background:rgba(255,255,255,.2);border-radius:12px;padding:10px 16px;font-size:28px;margin-bottom:12px">⚡</div>
    <h1 style="color:white;margin:0;font-size:22px;font-weight:800">¡Bienvenido a CuentaLuz Chile!</h1>
  </div>
  <div style="padding:28px 32px">
    <p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 16px">
      Gracias por suscribirte. Te avisaremos cuando:
    </p>
    <ul style="color:#374151;font-size:14px;line-height:2;padding-left:20px;margin:0 0 24px">
      <li>📊 Cambien las tarifas eléctricas (cada 6 meses, CNE)</li>
      <li>💡 Publiquemos análisis del mercado eléctrico chileno</li>
      <li>🏆 Lancemos nuevas funciones en la plataforma</li>
    </ul>
    <div style="background:#eff6ff;border-radius:12px;padding:20px;text-align:center;margin-bottom:24px">
      <p style="color:#1d4ed8;font-size:14px;margin:0 0 12px;font-weight:600">Calcula el desglose exacto de tu boleta:</p>
      <a href="{BASE_URL}" style="display:inline-block;background:#2563eb;color:white;font-weight:700;padding:12px 28px;border-radius:10px;text-decoration:none;font-size:14px">Ir a CuentaLuz →</a>
    </div>
    <p style="color:#9ca3af;font-size:12px;text-align:center;margin:0">
      Sin spam. Solo información útil sobre el mercado eléctrico chileno.<br>
      <a href="{url_baja}" style="color:#6b7280">Cancelar suscripción</a>
    </p>
  </div>
</div>
</body></html>"""

    text = (
        f"¡Bienvenido a CuentaLuz Chile!\n\n"
        f"Te avisaremos cuando cambien las tarifas eléctricas y publiquemos análisis del mercado.\n\n"
        f"Calcula tu boleta en: {BASE_URL}\n\n"
        f"Para cancelar la suscripción: {url_baja}\n"
    )
    return send(email, "¡Bienvenido a CuentaLuz Chile! ⚡", html, text)


def send_tariff_update(recipients: list[str], distribuidoras: list[str], cambios: list[str]) -> bool:
    if not recipients or not distribuidoras:
        return False

    dists_str   = ", ".join(d.upper() for d in distribuidoras)
    cambios_li  = "".join(
        f"<li style='margin:4px 0;font-size:13px;color:#374151'>{c.strip()}</li>"
        for c in cambios if c.strip()
    )
    cambios_blk = (
        f"<ul style='background:#f9fafb;border-radius:10px;padding:12px 24px;margin:0 0 20px'>{cambios_li}</ul>"
        if cambios_li else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:system-ui,sans-serif;background:#f8fafc;margin:0;padding:20px">
<div style="max-width:560px;margin:auto;background:white;border-radius:16px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
  <div style="background:linear-gradient(135deg,#1d4ed8,#3b82f6);padding:24px 32px;text-align:center">
    <h1 style="color:white;margin:0;font-size:20px;font-weight:800">📊 Tarifas eléctricas actualizadas</h1>
    <p style="color:#bfdbfe;margin:8px 0 0;font-size:14px">{dists_str}</p>
  </div>
  <div style="padding:28px 32px">
    <p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">
      Las tarifas de <strong>{dists_str}</strong> fueron actualizadas en CuentaLuz Chile.
      Recalcula tu boleta para obtener el estimado con los valores vigentes.
    </p>
    {cambios_blk}
    <div style="text-align:center;margin-bottom:24px">
      <a href="{BASE_URL}" style="display:inline-block;background:#2563eb;color:white;font-weight:700;padding:12px 28px;border-radius:10px;text-decoration:none;font-size:15px">
        Recalcular mi boleta →
      </a>
    </div>
    <p style="color:#9ca3af;font-size:12px;text-align:center;margin:0">CuentaLuz Chile · Herramienta educativa gratuita</p>
  </div>
</div>
</body></html>"""

    text = (
        f"Tarifas eléctricas actualizadas — {dists_str}\n\n"
        f"Recalcula tu boleta en: {BASE_URL}\n\n"
        + ("\n".join(cambios) if cambios else "")
    )
    return send(recipients, f"⚡ Tarifas {dists_str} actualizadas – CuentaLuz Chile", html, text)
