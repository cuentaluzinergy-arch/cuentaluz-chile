import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy import func
from database import SessionLocal
from app.models.benchmark import Benchmark
from app.services.benchmark_service import guardar as bm_guardar, stats_comuna as bm_stats
from app.services.calculator_service import (
    calcular_boleta,
    calcular_escenarios,
    calcular_solar,
    calcular_comparacion_tarifas,
    calcular_comparacion_distribuidoras,
    generar_recomendaciones,
    cargar_tarifas,
    cargar_aparatos,
    cargar_comunas,
    resolver_distribuidora,
)
from services.tarifa_service import get_metadata as _get_tarifa_meta

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    tarifas  = cargar_tarifas()
    aparatos = cargar_aparatos()
    comunas  = cargar_comunas()
    try:
        tarifa_meta = _get_tarifa_meta()
    except Exception:
        tarifa_meta = None

    conteo_calculos = 0
    db = SessionLocal()
    try:
        conteo_calculos = db.query(func.count(Benchmark.id)).scalar() or 0
    except Exception:
        pass
    finally:
        db.close()

    return templates.TemplateResponse(
        request, "index.html",
        {"tarifas": tarifas, "aparatos": aparatos,
         "comunas": comunas, "tarifa_meta": tarifa_meta,
         "conteo_calculos": conteo_calculos},
    )


@router.post("/calcular", response_class=HTMLResponse)
async def calcular(request: Request):
    form = await request.form()

    modo         = form.get("modo", "kwh")
    tarifa_tipo  = str(form.get("tarifa", "BT1")).strip()

    # Resolver distribuidora: primero por comuna, luego por selector directo
    nombre_comuna = str(form.get("comuna", "")).strip()
    distribuidora = str(form.get("distribuidora", "enel")).strip()
    if nombre_comuna:
        resuelta = resolver_distribuidora(nombre_comuna)
        if resuelta:
            distribuidora = resuelta

    # Validar distribuidora y tarifa
    tarifas_data = cargar_tarifas()
    if distribuidora not in tarifas_data:
        distribuidora = "enel"
    if tarifa_tipo not in ("BT1", "BT2"):
        tarifa_tipo = "BT1"

    # --- Calcular kWh ---
    if modo == "kwh":
        try:
            kwh = float(form.get("kwh_directo") or 0)
        except (ValueError, TypeError):
            kwh = 0.0
    else:
        aparatos = cargar_aparatos()
        kwh = 0.0
        for ap_id, ap_data in aparatos.items():
            if form.get(f"aparato_{ap_id}"):
                try:
                    horas = float(form.get(f"horas_{ap_id}") or ap_data["horas_dia_default"])
                except (ValueError, TypeError):
                    horas = ap_data["horas_dia_default"]
                kwh += (ap_data["potencia_w"] / 1000) * horas * 30
        kwh = round(kwh, 1)

    if kwh <= 0:
        try:
            tarifa_meta = _get_tarifa_meta()
        except Exception:
            tarifa_meta = None
        conteo_calculos = 0
        db = SessionLocal()
        try:
            conteo_calculos = db.query(func.count(Benchmark.id)).scalar() or 0
        except Exception:
            pass
        finally:
            db.close()
        return templates.TemplateResponse(
            request, "index.html",
            {
                "tarifas":        cargar_tarifas(),
                "aparatos":       cargar_aparatos(),
                "comunas":        cargar_comunas(),
                "tarifa_meta":    tarifa_meta,
                "conteo_calculos": conteo_calculos,
                "error":          "Ingresa un consumo mayor a 0 kWh o selecciona al menos un aparato.",
            },
        )

    resultado = calcular_boleta(kwh, distribuidora, tarifa_tipo)
    escenarios = calcular_escenarios(resultado, distribuidora, tarifa_tipo)
    solar = calcular_solar(resultado)
    comparacion_tarifas = calcular_comparacion_tarifas(kwh, distribuidora)
    comparacion_distribuidoras = calcular_comparacion_distribuidoras(kwh, tarifa_tipo)
    recomendaciones = generar_recomendaciones(resultado, distribuidora)

    # Benchmark comunal: guardar consumo anónimo y obtener stats
    benchmark = None
    if nombre_comuna:
        db = SessionLocal()
        try:
            bm_guardar(db, nombre_comuna, distribuidora, int(kwh))
            benchmark = bm_stats(db, nombre_comuna, int(kwh))
        except Exception:
            pass
        finally:
            db.close()

    return templates.TemplateResponse(
        request, "resultados.html",
        {
            "resultado":                 resultado,
            "escenarios":                escenarios,
            "solar":                     solar,
            "comparacion_tarifas":       comparacion_tarifas,
            "comparacion_distribuidoras": comparacion_distribuidoras,
            "recomendaciones":           recomendaciones,
            "comuna":                    nombre_comuna or None,
            "benchmark":                 benchmark,
        },
    )


@router.get("/comunas", response_class=HTMLResponse)
async def comunas(request: Request):
    comunas_raw = cargar_comunas()
    tarifas = cargar_tarifas()

    # Agrupar por distribuidora
    grupos: dict[str, list] = {}
    for c in comunas_raw:
        did = c["distribuidora_id"]
        grupos.setdefault(did, []).append(c)

    # Metadata de distribuidoras para el template
    dist_meta = {
        did: {"nombre": tarifas[did]["nombre"], "region": tarifas[did]["region"]}
        for did in grupos if did in tarifas
    }

    try:
        tarifa_meta = _get_tarifa_meta()
    except Exception:
        tarifa_meta = None

    return templates.TemplateResponse(
        request, "comunas.html",
        {
            "grupos":     grupos,
            "dist_meta":  dist_meta,
            "total":      len(comunas_raw),
            "tarifa_meta": tarifa_meta,
        },
    )
