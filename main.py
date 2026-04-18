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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import engine, Base
from app.routes import calculator, newsletter, gis

logger = logging.getLogger(__name__)

# Crear tablas si no existen
import app.models.subscriber  # noqa: F401 – registra el modelo
import app.models.sec_cache   # noqa: F401 – registra el modelo
Base.metadata.create_all(bind=engine)

from contextlib import asynccontextmanager

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

# Archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

# Registrar rutas
app.include_router(calculator.router)
app.include_router(newsletter.router)
app.include_router(gis.router)

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
