from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from database import SessionLocal
from app.models.desafio import Desafio
from app.services.rate_limiter import allow, client_ip
from services.tarifa_service import get_metadata as _get_tarifa_meta

router = APIRouter()
templates = Jinja2Templates(directory="templates")

MESES_ES = {
    1:"enero", 2:"febrero", 3:"marzo", 4:"abril", 5:"mayo", 6:"junio",
    7:"julio", 8:"agosto", 9:"septiembre", 10:"octubre", 11:"noviembre", 12:"diciembre",
}


def _mes_actual() -> str:
    return datetime.now().strftime("%Y-%m")


def _nombre_mes(mes_str: str) -> str:
    try:
        y, m = mes_str.split("-")
        return f"{MESES_ES[int(m)].capitalize()} {y}"
    except Exception:
        return mes_str


@router.get("/desafio", response_class=HTMLResponse)
async def desafio_page(request: Request):
    mes = _mes_actual()
    db = SessionLocal()
    try:
        top = (
            db.query(Desafio)
            .filter(Desafio.mes == mes, Desafio.reduccion_pct > 0)
            .order_by(Desafio.reduccion_pct.desc())
            .limit(20)
            .all()
        )
        total_mes = db.query(Desafio).filter(Desafio.mes == mes).count()
    finally:
        db.close()

    try:
        tarifa_meta = _get_tarifa_meta()
    except Exception:
        tarifa_meta = None

    return templates.TemplateResponse(
        request, "desafio.html",
        {
            "top":          top,
            "total_mes":    total_mes,
            "nombre_mes":   _nombre_mes(mes),
            "tarifa_meta":  tarifa_meta,
        },
    )


@router.post("/api/desafio", response_class=JSONResponse)
async def registrar_desafio(request: Request):
    if not allow(f"desafio:{client_ip(request)}", limit=3, window=3600):
        return JSONResponse({"ok": False, "error": "Ya registraste varias entradas. Intenta en 1 hora."}, status_code=429)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido"}, status_code=400)

    try:
        kwh_ant = int(data.get("kwh_anterior", 0))
        kwh_act = int(data.get("kwh_actual", 0))
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "Consumos inválidos."}, status_code=422)

    if not (1 <= kwh_ant <= 5000) or not (1 <= kwh_act <= 5000):
        return JSONResponse({"ok": False, "error": "Consumo fuera de rango (1–5000 kWh)."}, status_code=422)

    reduccion_pct = round((kwh_ant - kwh_act) / kwh_ant * 100, 1)
    nickname = str(data.get("nickname", "")).strip()[:50] or None
    comuna   = str(data.get("comuna", "")).strip()[:100] or None
    mes      = _mes_actual()

    db = SessionLocal()
    try:
        entry = Desafio(
            nickname=nickname,
            kwh_anterior=kwh_ant,
            kwh_actual=kwh_act,
            reduccion_pct=reduccion_pct,
            comuna=comuna,
            mes=mes,
        )
        db.add(entry)
        db.commit()

        # Posición en el ranking (solo entradas con reducción positiva)
        if reduccion_pct > 0:
            posicion = (
                db.query(Desafio)
                .filter(Desafio.mes == mes, Desafio.reduccion_pct > reduccion_pct)
                .count()
            ) + 1
        else:
            posicion = None

        total = db.query(Desafio).filter(Desafio.mes == mes).count()

    except Exception:
        db.rollback()
        return JSONResponse({"ok": False, "error": "Error al guardar."}, status_code=500)
    finally:
        db.close()

    return JSONResponse({
        "ok":           True,
        "reduccion_pct": reduccion_pct,
        "kwh_ahorrado": kwh_ant - kwh_act,
        "posicion":     posicion,
        "total":        total,
        "nombre_mes":   _nombre_mes(mes),
    })
