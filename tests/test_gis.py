"""
tests/test_gis.py

Tests unitarios del módulo SEC GIS (sin red, sin base de datos).

Ejecutar con:
    pytest tests/test_gis.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta


# ── Helpers de mock ────────────────────────────────────────────────────────────

def _nominatim_resp(ciudad: str) -> dict:
    """Respuesta Nominatim simulada para una ciudad chilena."""
    return {
        "address": {
            "city": ciudad,
            "country_code": "cl",
        }
    }


def _nominatim_resp_town(town: str) -> dict:
    """Nominatim sin 'city', solo 'town' (localidades menores)."""
    return {
        "address": {
            "town": town,
            "country_code": "cl",
        }
    }


# ── Tests principales ──────────────────────────────────────────────────────────

class TestResolverPorCoordenadas:
    """
    Verifica que resolver_por_coordenadas() asigna correctamente la distribuidora
    para las cuatro distribuidoras del sistema.
    """

    def _call(self, ciudad: str, monkeypatch, resp_fn=None) -> dict:
        if resp_fn is None:
            resp_fn = _nominatim_resp
        monkeypatch.setattr(
            "services.sec_gis_service._nominatim_reverse",
            lambda lat, lon: resp_fn(ciudad),
        )
        from services.sec_gis_service import resolver_por_coordenadas
        return resolver_por_coordenadas(0.0, 0.0, db=None)

    def test_santiago_enel(self, monkeypatch):
        """Santiago → enel (RM)."""
        result = self._call("Santiago", monkeypatch)
        assert result.get("distribuidora_id") == "enel"
        assert result["comuna"] == "Santiago"
        assert result["fuente"] == "nominatim"

    def test_concepcion_cge(self, monkeypatch):
        """Concepción → cge."""
        result = self._call("Concepción", monkeypatch)
        assert result.get("distribuidora_id") == "cge"

    def test_valparaiso_chilquinta(self, monkeypatch):
        """Valparaíso → chilquinta."""
        result = self._call("Valparaíso", monkeypatch)
        assert result.get("distribuidora_id") == "chilquinta"

    def test_temuco_frontel(self, monkeypatch):
        """Temuco → frontel (IX Región)."""
        result = self._call("Temuco", monkeypatch)
        assert result.get("distribuidora_id") == "frontel"

    def test_nombre_via_town(self, monkeypatch):
        """Nominatim entrega 'town' en vez de 'city' → igual se resuelve."""
        result = self._call("Villarrica", monkeypatch, resp_fn=_nominatim_resp_town)
        assert result.get("distribuidora_id") == "frontel"

    def test_comuna_inexistente_retorna_error(self, monkeypatch):
        """Comuna desconocida → retorna dict con 'error', sin excepción."""
        monkeypatch.setattr(
            "services.sec_gis_service._nominatim_reverse",
            lambda lat, lon: {"address": {"city": "ComunaFicticia999"}},
        )
        from services.sec_gis_service import resolver_por_coordenadas
        result = resolver_por_coordenadas(0.0, 0.0, db=None)
        assert "error" in result
        assert "ComunaFicticia999" in result["error"]

    def test_nominatim_fallo_retorna_error(self, monkeypatch):
        """Si Nominatim lanza excepción → retorna dict con 'error'."""
        monkeypatch.setattr(
            "services.sec_gis_service._nominatim_reverse",
            lambda lat, lon: (_ for _ in ()).throw(OSError("timeout")),
        )
        from services.sec_gis_service import resolver_por_coordenadas
        result = resolver_por_coordenadas(0.0, 0.0, db=None)
        assert "error" in result

    def test_nominatim_sin_address_retorna_error(self, monkeypatch):
        """Nominatim retorna respuesta vacía → retorna dict con 'error'."""
        monkeypatch.setattr(
            "services.sec_gis_service._nominatim_reverse",
            lambda lat, lon: {},
        )
        from services.sec_gis_service import resolver_por_coordenadas
        result = resolver_por_coordenadas(0.0, 0.0, db=None)
        assert "error" in result


class TestCache:
    """Verifica que el caché SQLite funciona correctamente."""

    def _make_db_con_cache(self, dist_id: str, dias_atras: int):
        """Crea un mock de sesión DB con una entrada de caché."""
        from app.models.sec_cache import SecCache
        entry = MagicMock(spec=SecCache)
        entry.distribuidora_id = dist_id
        entry.fecha_consulta = date.today() - timedelta(days=dias_atras)

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = entry
        return db

    def test_cache_vigente_retorna_fuente_cache(self, monkeypatch):
        """
        Caché válido (<180 días) → fuente='cache' y no se escribe en DB.
        Nota: Nominatim igualmente se llama para resolver el nombre de comuna;
        el caché evita el lookup local y la escritura a DB.
        """
        monkeypatch.setattr(
            "services.sec_gis_service._nominatim_reverse",
            lambda lat, lon: {"address": {"city": "Santiago"}},
        )

        db = self._make_db_con_cache("enel", dias_atras=10)

        from services.sec_gis_service import resolver_por_coordenadas
        result = resolver_por_coordenadas(-33.4, -70.6, db=db)

        assert result["distribuidora_id"] == "enel"
        assert result["fuente"] == "cache"
        # No debe haber escritura a DB en un hit de caché
        db.add.assert_not_called()

    def test_cache_expirado_llama_nominatim(self, monkeypatch):
        """Caché expirado (>180 días) → debe llamar a Nominatim."""
        nominatim_llamado = []

        monkeypatch.setattr(
            "services.sec_gis_service._nominatim_reverse",
            lambda lat, lon: nominatim_llamado.append(True) or {"address": {"city": "Santiago"}},
        )

        db = self._make_db_con_cache("enel", dias_atras=200)

        from services.sec_gis_service import resolver_por_coordenadas
        resolver_por_coordenadas(-33.4, -70.6, db=db)

        assert len(nominatim_llamado) == 1


class TestExtraerComuna:
    """Tests unitarios de _extraer_comuna()."""

    def test_extrae_city(self):
        from services.sec_gis_service import _extraer_comuna
        assert _extraer_comuna({"address": {"city": "Santiago"}}) == "Santiago"

    def test_extrae_town_si_no_city(self):
        from services.sec_gis_service import _extraer_comuna
        assert _extraer_comuna({"address": {"town": "Pucón"}}) == "Pucón"

    def test_extrae_village_si_no_town(self):
        from services.sec_gis_service import _extraer_comuna
        assert _extraer_comuna({"address": {"village": "Curarrehue"}}) == "Curarrehue"

    def test_retorna_none_si_vacio(self):
        from services.sec_gis_service import _extraer_comuna
        assert _extraer_comuna({}) is None
        assert _extraer_comuna({"address": {}}) is None
