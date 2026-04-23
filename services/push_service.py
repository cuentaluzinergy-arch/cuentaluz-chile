"""
Servicio Web Push (VAPID) — CuentaLuz Chile.

Claves VAPID:
  - Lee VAPID_PRIVATE_KEY (PEM) y VAPID_PUBLIC_KEY (URL-safe base64) del entorno.
  - Si no están configuradas, las genera automáticamente y las guarda en
    data/vapid_keys.json (solo para desarrollo — en producción usar env vars).

Uso:
    from services.push_service import get_public_key, send_push, notify_tariff_update
"""
import base64
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT      = Path(__file__).resolve().parent.parent
_KEYS_FILE = _ROOT / "data" / "vapid_keys.json"
_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)

_CONTACT = os.getenv("ALERT_EMAIL", "admin@cuentaluz.cl")

# ── Gestión de claves VAPID ────────────────────────────────────────────────────

def _generate_keys() -> tuple[str, str]:
    """Genera un par de claves VAPID y devuelve (private_pem, public_b64)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption,
    )
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key  = private_key.public_key()

    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    ).decode()

    public_raw = public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    public_b64 = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode()

    return private_pem, public_b64


def _load_or_generate() -> tuple[str, str]:
    """Devuelve (private_pem, public_b64) — desde env, archivo o generadas."""
    private = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    public  = os.getenv("VAPID_PUBLIC_KEY",  "").strip()

    if private and public:
        return private, public

    if _KEYS_FILE.exists():
        try:
            data    = json.loads(_KEYS_FILE.read_text())
            private = data["private_key"]
            public  = data["public_key"]
            if private and public:
                return private, public
        except Exception:
            pass

    # Generar nuevas
    logger.warning("Generando claves VAPID nuevas. Configura VAPID_PRIVATE_KEY y VAPID_PUBLIC_KEY en .env para producción.")
    private, public = _generate_keys()
    _KEYS_FILE.write_text(json.dumps({"private_key": private, "public_key": public}, indent=2))
    logger.info(f"Claves VAPID guardadas en {_KEYS_FILE}")
    logger.info(f"VAPID public key: {public}")
    return private, public


_private_key: str = ""
_public_key:  str = ""


def _keys() -> tuple[str, str]:
    global _private_key, _public_key
    if not _private_key:
        _private_key, _public_key = _load_or_generate()
    return _private_key, _public_key


def get_public_key() -> str:
    return _keys()[1]


# ── Envío ──────────────────────────────────────────────────────────────────────

def send_push(endpoint: str, p256dh: str, auth: str, payload: dict) -> bool:
    """Envía una notificación Web Push a una suscripción. Devuelve True si tuvo éxito."""
    try:
        from pywebpush import webpush, WebPushException
        private_pem, _ = _keys()
        webpush(
            subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=private_pem,
            vapid_claims={"sub": f"mailto:{_CONTACT}"},
            content_encoding="aes128gcm",
        )
        return True
    except Exception as e:
        logger.error(f"Error enviando push a {endpoint[:40]}…: {e}")
        return False


def notify_tariff_update(distribuidoras: list[str]) -> int:
    """Notifica a todos los suscriptores push. Devuelve el número de envíos exitosos."""
    try:
        from database import SessionLocal
        from app.models.push_subscription import PushSubscription
        db = SessionLocal()
        try:
            subs = db.query(PushSubscription).all()
        finally:
            db.close()
    except Exception as e:
        logger.error(f"No se pudo consultar suscripciones push: {e}")
        return 0

    if not subs:
        return 0

    dists_str = ", ".join(d.upper() for d in distribuidoras)
    payload = {
        "title": "⚡ Tarifas eléctricas actualizadas",
        "body":  f"Se actualizaron las tarifas de {dists_str}. Recalcula tu boleta.",
        "url":   "/",
        "icon":  "/static/icons/icon-192.svg",
        "badge": "/static/icons/icon-192.svg",
    }

    ok = 0
    stale = []
    for sub in subs:
        if send_push(sub.endpoint, sub.p256dh, sub.auth, payload):
            ok += 1
        else:
            stale.append(sub.endpoint)

    # Eliminar suscripciones que fallaron (endpoint expirado)
    if stale:
        try:
            from database import SessionLocal
            from app.models.push_subscription import PushSubscription
            db = SessionLocal()
            try:
                db.query(PushSubscription).filter(
                    PushSubscription.endpoint.in_(stale)
                ).delete(synchronize_session=False)
                db.commit()
                logger.info(f"Eliminadas {len(stale)} suscripciones push expiradas")
            finally:
                db.close()
        except Exception:
            pass

    logger.info(f"Push enviado: {ok}/{len(subs)} exitosos")
    return ok
