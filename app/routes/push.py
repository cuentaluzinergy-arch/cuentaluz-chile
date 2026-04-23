from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database import SessionLocal
from app.models.push_subscription import PushSubscription
from app.services.rate_limiter import allow, client_ip
from services.push_service import get_public_key

router = APIRouter()


@router.get("/api/push/vapid-public-key", response_class=JSONResponse)
async def vapid_public_key():
    return JSONResponse({"publicKey": get_public_key()})


@router.post("/api/push/subscribe", response_class=JSONResponse)
async def subscribe(request: Request):
    if not allow(f"push:{client_ip(request)}", limit=10, window=3600):
        return JSONResponse({"ok": False, "error": "Demasiadas solicitudes."}, status_code=429)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido"}, status_code=400)

    endpoint = str(data.get("endpoint", "")).strip()
    p256dh   = str(data.get("p256dh", "")).strip()
    auth     = str(data.get("auth", "")).strip()

    if not endpoint or not p256dh or not auth:
        return JSONResponse({"ok": False, "error": "Faltan datos de suscripción."}, status_code=422)

    ua = request.headers.get("user-agent", "")[:200]

    db = SessionLocal()
    try:
        existing = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
        if existing:
            return JSONResponse({"ok": True, "mensaje": "Ya estás suscrito."})

        sub = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=ua)
        db.add(sub)
        db.commit()
        return JSONResponse({"ok": True, "mensaje": "Notificaciones activadas."})
    except Exception:
        db.rollback()
        return JSONResponse({"ok": False, "error": "Error al guardar."}, status_code=500)
    finally:
        db.close()


@router.post("/api/push/unsubscribe", response_class=JSONResponse)
async def unsubscribe(request: Request):
    try:
        data     = await request.json()
        endpoint = str(data.get("endpoint", "")).strip()
    except Exception:
        return JSONResponse({"ok": False}, status_code=400)

    if not endpoint:
        return JSONResponse({"ok": False}, status_code=422)

    db = SessionLocal()
    try:
        db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).delete()
        db.commit()
        return JSONResponse({"ok": True})
    except Exception:
        db.rollback()
        return JSONResponse({"ok": False}, status_code=500)
    finally:
        db.close()
