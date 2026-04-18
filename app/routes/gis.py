"""
Rutas GIS — resolución de distribuidora por coordenadas GPS.

GET /api/gis/distribuidora?lat=<float>&lon=<float>
  200 → {"distribuidora_id": "enel", "comuna": "Santiago", "fuente": "nominatim"}
  422 → {"detail": "..."}  en caso de falla
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from services.sec_gis_service import resolver_por_coordenadas

router = APIRouter(prefix="/api/gis", tags=["gis"])


@router.get("/distribuidora")
async def distribuidora_por_gps(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitud"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Longitud"),
    db: Session = Depends(get_db),
):
    """Retorna la distribuidora eléctrica a partir de coordenadas GPS."""
    resultado = resolver_por_coordenadas(lat, lon, db=db)
    if "error" in resultado:
        raise HTTPException(status_code=422, detail=resultado["error"])
    return resultado
