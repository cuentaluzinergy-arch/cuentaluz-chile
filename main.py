"""
CuentaLuz Chile – Punto de entrada principal.

Ejecutar en desarrollo:
    python main.py
    uvicorn main:app --reload

Deploy en Railway/Render:
    uvicorn main:app --host 0.0.0.0 --port $PORT

Variables de entorno (ver .env.example):
    ENABLE_SCHEDULER=true   → activa actualizacion automatica mensual
    TARIFF_UPDATE_DAY=1     → dia del mes para la actualizacion
"""
import logging
import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import engine, Base
from app.routes import calculator, newsletter, gis, tips, desafio, push

logger = logging.getLogger(__name__)

# Crear tablas si no existen
import app.models.subscriber  # noqa: F401 – registra el modelo
import app.models.sec_cache   # noqa: F401 – registra el modelo
import app.models.benchmark   # noqa: F401 – registra el modelo
import app.models.tip         # noqa: F401 – registra el modelo
import app.models.desafio           # noqa: F401 – registra el modelo
import app.models.push_subscription  # noqa: F401 – registra el modelo
Base.metadata.create_all(bind=engine)

from contextlib import asynccontextmanager

def _migrate_db() -> None:
    """Agrega columnas nuevas a tablas existentes sin romper datos previos."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE subscribers ADD COLUMN token VARCHAR(36)",
        "ALTER TABLE subscribers ADD COLUMN activo BOOLEAN DEFAULT 1",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # columna ya existe

        # Generar tokens para suscriptores existentes sin token
        import uuid
        rows = conn.execute(text("SELECT id FROM subscribers WHERE token IS NULL")).fetchall()
        for row in rows:
            conn.execute(
                text("UPDATE subscribers SET token = :t WHERE id = :id"),
                {"t": str(uuid.uuid4()), "id": row[0]},
            )
        if rows:
            conn.commit()


_migrate_db()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Lifespan: arranca el scheduler al iniciar, lo detiene al apagar."""
    if os.getenv("ENABLE_SCHEDULER", "false").lower() == "true":
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from services.updater import run_update

            scheduler = BackgroundScheduler(timezone="America/Santiago")
            day = int(os.getenv("TARIFF_UPDATE_DAY", "1"))
            scheduler.add_job(run_update, "cron", day=day, hour=8, minute=0)
            scheduler.start()
            application.state.scheduler = scheduler
            logger.info(f"Scheduler activo: actualizacion tarifas dia {day} de cada mes a las 08:00 CLT")
        except Exception as e:
            logger.warning(f"No se pudo iniciar el scheduler: {e}")

    yield

    if hasattr(application.state, "scheduler"):
        application.state.scheduler.shutdown(wait=False)


app = FastAPI(
    title="CuentaLuz Chile",
    description="Calculadora de cuenta de luz residencial para Chile",
    version="1.0.0",
    lifespan=lifespan,
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"]           = "DENY"
        response.headers["X-Content-Type-Options"]    = "nosniff"
        response.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]        = "geolocation=(), microphone=(), camera=()"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

# Registrar rutas
app.include_router(calculator.router)
app.include_router(newsletter.router)
app.include_router(gis.router)
app.include_router(tips.router)
app.include_router(desafio.router)
app.include_router(push.router)

# Filtro de formato de moneda para Jinja2
import jinja2  # noqa: E402
from fastapi.templating import Jinja2Templates as _T  # noqa: E402


def _format_clp(value) -> str:
    """Formatea un número como peso chileno: $1.234.567"""
    try:
        return "${:,.0f}".format(int(value)).replace(",", ".")
    except (ValueError, TypeError):
        return "$0"


# Registrar filtro en el router de la calculadora
calculator.templates = _T(directory="templates")
calculator.templates.env.filters["clp"] = _format_clp


# Archivos SEO en raíz
from fastapi.exceptions import HTTPException
from fastapi.templating import Jinja2Templates as _Tmpl

_tmpl_err = _Tmpl(directory="templates")

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return _tmpl_err.TemplateResponse(request, "404.html", status_code=404)


@app.get("/privacidad", response_class=HTMLResponse, include_in_schema=False)
async def privacidad(request: Request):
    from fastapi.templating import Jinja2Templates as _TT
    return _TT(directory="templates").TemplateResponse(request, "privacidad.html", {"tarifa_meta": None})


@app.get("/offline", response_class=HTMLResponse, include_in_schema=False)
async def offline(request: Request):
    from fastapi.templating import Jinja2Templates as _TT
    return _TT(directory="templates").TemplateResponse(request, "offline.html", {"tarifa_meta": None})


@app.get("/manifest.json", include_in_schema=False)
async def manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    return FileResponse("static/robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    return FileResponse("static/sitemap.xml", media_type="application/xml")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
