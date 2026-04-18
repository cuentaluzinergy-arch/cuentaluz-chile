from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import get_db
from app.models.subscriber import Subscriber

router = APIRouter()


@router.post("/api/newsletter")
async def subscribe(request: Request, db: Session = Depends(get_db)):
    """
    Suscribe un email al newsletter.
    Acepta tanto JSON como datos de formulario.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
        fuente = str(body.get("fuente", "calculadora"))
    else:
        form = await request.form()
        email = str(form.get("email", "")).strip().lower()
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
        return JSONResponse(
            {
                "success": True,
                "mensaje": "¡Suscrito! Te avisaremos cuando publiquemos nuevos análisis del mercado eléctrico.",
            }
        )
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
