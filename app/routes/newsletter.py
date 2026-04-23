from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import get_db
from app.models.subscriber import Subscriber
from app.services.rate_limiter import allow, client_ip

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.post("/api/newsletter")
async def subscribe(request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not allow(f"newsletter:{ip}", limit=3, window=3600):
        return JSONResponse(
            {"success": False, "mensaje": "Demasiados intentos. Espera un momento."},
            status_code=429,
        )

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        email  = str(body.get("email", "")).strip().lower()
        fuente = str(body.get("fuente", "calculadora"))
    else:
        form   = await request.form()
        email  = str(form.get("email", "")).strip().lower()
        fuente = str(form.get("fuente", "calculadora"))

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return JSONResponse(
            {"success": False, "mensaje": "Por favor ingresa un email válido."},
            status_code=400,
        )

    try:
        subscriber = Subscriber(email=email, fuente=fuente)
        db.add(subscriber)
        db.commit()
        db.refresh(subscriber)

        # Email de bienvenida (falla silenciosamente si SMTP no está configurado)
        try:
            from services.email_service import send_welcome
            send_welcome(email, subscriber.token or "")
        except Exception:
            pass

        return JSONResponse({
            "success": True,
            "mensaje": "¡Suscrito! Revisa tu correo para confirmar.",
        })
    except IntegrityError:
        db.rollback()
        return JSONResponse(
            {"success": True, "mensaje": "Ya estás suscrito. ¡Gracias por tu interés!"}
        )
    except Exception:
        db.rollback()
        return JSONResponse(
            {"success": False, "mensaje": "Ocurrió un error. Por favor intenta de nuevo."},
            status_code=500,
        )


@router.get("/newsletter/baja", response_class=HTMLResponse)
async def unsubscribe(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not token:
        return templates.TemplateResponse(request, "newsletter_baja.html", {
            "icono": "❌",
            "titulo": "Enlace inválido",
            "mensaje": "El enlace de baja no es válido. Si deseas darte de baja escríbenos a contacto@cuentaluz.cl.",
        }, status_code=400)

    sub = db.query(Subscriber).filter(Subscriber.token == token).first()
    if not sub:
        return templates.TemplateResponse(request, "newsletter_baja.html", {
            "icono": "🤔",
            "titulo": "Enlace no encontrado",
            "mensaje": "No encontramos una suscripción con este enlace. Es posible que ya hayas dado de baja anteriormente.",
        }, status_code=404)

    db.delete(sub)
    db.commit()
    return templates.TemplateResponse(request, "newsletter_baja.html", {
        "icono": "✅",
        "titulo": "Baja exitosa",
        "mensaje": "Tu correo fue eliminado de nuestra lista. No recibirás más emails de CuentaLuz Chile.",
    })
