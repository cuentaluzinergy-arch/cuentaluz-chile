from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from database import SessionLocal
from app.models.tip import Tip
from app.services.rate_limiter import allow, client_ip
from services.tarifa_service import get_metadata as _get_tarifa_meta

router = APIRouter()
templates = Jinja2Templates(directory="templates")

CATEGORIAS = {
    "iluminacion": {"label": "Iluminación",       "emoji": "💡"},
    "refrigerador": {"label": "Refrigerador",     "emoji": "🧊"},
    "agua_caliente": {"label": "Agua caliente",   "emoji": "🚿"},
    "climatizacion": {"label": "Calefacción/Frío","emoji": "🌡️"},
    "electronica":  {"label": "Electrónica",       "emoji": "🖥️"},
    "habitos":      {"label": "Hábitos",           "emoji": "🌿"},
    "solar":        {"label": "Solar",             "emoji": "☀️"},
}

MAX_TEXTO   = 400
MIN_TEXTO   = 20
MAX_AHORRO  = 50
PAGE_SIZE   = 20


def _serialize_tip(t: Tip) -> dict:
    return {
        "id":              t.id,
        "texto":           t.texto,
        "categoria":       t.categoria,
        "ahorro_estimado": t.ahorro_estimado,
        "comuna":          t.comuna,
        "likes":           t.likes,
        "fecha":           t.fecha.strftime("%d/%m/%Y") if t.fecha else "",
    }


@router.get("/tips", response_class=HTMLResponse)
async def feed(request: Request, page: int = 1):
    page = max(1, page)
    db = SessionLocal()
    try:
        total = db.query(Tip).filter(Tip.aprobado == True).count()  # noqa: E712
        tips = (
            db.query(Tip)
            .filter(Tip.aprobado == True)          # noqa: E712
            .order_by(Tip.likes.desc(), Tip.fecha.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
            .all()
        )
    finally:
        db.close()

    try:
        tarifa_meta = _get_tarifa_meta()
    except Exception:
        tarifa_meta = None

    return templates.TemplateResponse(
        request, "tips.html",
        {
            "tips":        tips,
            "categorias":  CATEGORIAS,
            "tarifa_meta": tarifa_meta,
            "total":       total,
            "page":        page,
            "page_size":   PAGE_SIZE,
            "has_more":    (page * PAGE_SIZE) < total,
        },
    )


@router.get("/api/tips", response_class=JSONResponse)
async def api_tips(request: Request, page: int = 1):
    page = max(1, page)
    db = SessionLocal()
    try:
        total = db.query(Tip).filter(Tip.aprobado == True).count()  # noqa: E712
        tips = (
            db.query(Tip)
            .filter(Tip.aprobado == True)          # noqa: E712
            .order_by(Tip.likes.desc(), Tip.fecha.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
            .all()
        )
        return JSONResponse({
            "tips":     [_serialize_tip(t) for t in tips],
            "total":    total,
            "page":     page,
            "has_more": (page * PAGE_SIZE) < total,
        })
    finally:
        db.close()


@router.get("/tips/rss", include_in_schema=False)
async def tips_rss():
    import xml.etree.ElementTree as ET
    from datetime import timezone
    base = "https://cuentaluz.cl"
    db = SessionLocal()
    try:
        tips = (
            db.query(Tip)
            .filter(Tip.aprobado == True)           # noqa: E712
            .order_by(Tip.fecha.desc())
            .limit(30)
            .all()
        )
    finally:
        db.close()

    rss = ET.Element("rss", version="2.0")
    ch  = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text         = "CuentaLuz Chile — Consejos de ahorro"
    ET.SubElement(ch, "link").text          = f"{base}/tips"
    ET.SubElement(ch, "description").text   = "Consejos reales de hogares chilenos para reducir la cuenta de la luz."
    ET.SubElement(ch, "language").text      = "es-cl"
    ET.SubElement(ch, "lastBuildDate").text = tips[0].fecha.strftime("%a, %d %b %Y %H:%M:%S +0000") if tips else ""

    for t in tips:
        item  = ET.SubElement(ch, "item")
        cat   = CATEGORIAS.get(t.categoria, {})
        label = cat.get("label", t.categoria)
        ET.SubElement(item, "title").text       = f"[{label}] {t.texto[:60]}{'…' if len(t.texto) > 60 else ''}"
        ET.SubElement(item, "link").text        = f"{base}/tips"
        ET.SubElement(item, "description").text = t.texto + (f" Ahorro: {t.ahorro_estimado}" if t.ahorro_estimado else "")
        ET.SubElement(item, "guid").text        = f"{base}/tips#{t.id}"
        if t.fecha:
            ET.SubElement(item, "pubDate").text = t.fecha.strftime("%a, %d %b %Y %H:%M:%S +0000")

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")
    return Response(content=xml_str, media_type="application/rss+xml; charset=utf-8")


@router.post("/api/tips", response_class=JSONResponse)
async def crear_tip(request: Request):
    if not allow(f"tips:{client_ip(request)}", limit=5, window=3600):
        return JSONResponse({"ok": False, "error": "Demasiados consejos enviados. Intenta en 1 hora."}, status_code=429)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido"}, status_code=400)

    texto    = str(data.get("texto", "")).strip()
    ahorro   = str(data.get("ahorro_estimado", "")).strip()[:MAX_AHORRO]
    categoria = str(data.get("categoria", "habitos")).strip()
    comuna   = str(data.get("comuna", "")).strip()[:100]

    if len(texto) < MIN_TEXTO:
        return JSONResponse({"ok": False, "error": f"El consejo debe tener al menos {MIN_TEXTO} caracteres."}, status_code=422)
    if len(texto) > MAX_TEXTO:
        return JSONResponse({"ok": False, "error": f"Máximo {MAX_TEXTO} caracteres."}, status_code=422)
    if categoria not in CATEGORIAS:
        categoria = "habitos"

    db = SessionLocal()
    try:
        tip = Tip(
            texto=texto,
            ahorro_estimado=ahorro or None,
            categoria=categoria,
            comuna=comuna or None,
        )
        db.add(tip)
        db.commit()
        db.refresh(tip)
        return JSONResponse({
            "ok": True,
            "id": tip.id,
            "mensaje": "¡Gracias! Tu consejo fue publicado.",
        })
    except Exception:
        db.rollback()
        return JSONResponse({"ok": False, "error": "Error al guardar."}, status_code=500)
    finally:
        db.close()


@router.post("/api/tips/{tip_id}/like", response_class=JSONResponse)
async def like_tip(tip_id: int, request: Request):
    db = SessionLocal()
    try:
        tip = db.query(Tip).filter(Tip.id == tip_id, Tip.aprobado == True).first()  # noqa: E712
        if not tip:
            return JSONResponse({"ok": False}, status_code=404)
        tip.likes += 1
        db.commit()
        return JSONResponse({"ok": True, "likes": tip.likes})
    except Exception:
        db.rollback()
        return JSONResponse({"ok": False}, status_code=500)
    finally:
        db.close()
