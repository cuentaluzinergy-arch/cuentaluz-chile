"""
tests/test_integration.py

Tests de integración para los endpoints HTTP de CuentaLuz.
Usan TestClient (starlette) con la app FastAPI en memoria (sin red, sin puerto real).

Ejecutar con:
    pytest tests/test_integration.py -v
"""
import pytest
from starlette.testclient import TestClient
from main import app


# ── Fixture compartida ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """Cliente HTTP síncrono con la app montada en memoria."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── GET / ─────────────────────────────────────────────────────────────────────

class TestIndex:
    def test_get_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_html_contiene_calculadora(self, client):
        resp = client.get("/")
        assert "CuentaLuz" in resp.text
        assert "kWh" in resp.text

    def test_html_contiene_comunas_en_datalist(self, client):
        resp = client.get("/")
        assert "Santiago" in resp.text

    def test_html_contiene_boton_gps(self, client):
        resp = client.get("/")
        assert "btn-gps" in resp.text


# ── POST /calcular ─────────────────────────────────────────────────────────────

class TestCalcular:
    def _post(self, client, kwh=250, distribuidora="enel", tarifa="BT1", modo="kwh"):
        return client.post(
            "/calcular",
            data={
                "modo":          modo,
                "kwh_directo":   str(kwh),
                "distribuidora": distribuidora,
                "tarifa":        tarifa,
            },
        )

    def test_post_enel_bt1_250kwh_200(self, client):
        resp = self._post(client, kwh=250, distribuidora="enel")
        assert resp.status_code == 200

    def test_resultado_muestra_total(self, client):
        resp = self._post(client, kwh=250, distribuidora="enel")
        # El total debe estar en el HTML (tiene signo $)
        assert "$" in resp.text
        assert "kWh" in resp.text

    def test_cge_bt1_300kwh(self, client):
        resp = self._post(client, kwh=300, distribuidora="cge")
        assert resp.status_code == 200

    def test_chilquinta_bt1_200kwh(self, client):
        resp = self._post(client, kwh=200, distribuidora="chilquinta")
        assert resp.status_code == 200

    def test_frontel_bt1_400kwh(self, client):
        resp = self._post(client, kwh=400, distribuidora="frontel")
        assert resp.status_code == 200

    def test_bt2_tarifa(self, client):
        resp = self._post(client, kwh=300, distribuidora="enel", tarifa="BT2")
        assert resp.status_code == 200

    def test_kwh_cero_retorna_error(self, client):
        resp = self._post(client, kwh=0, distribuidora="enel")
        assert resp.status_code == 200
        assert "error" in resp.text.lower() or "ingresa" in resp.text.lower()

    def test_distribuidor_invalido_usa_fallback_enel(self, client):
        resp = client.post(
            "/calcular",
            data={"modo": "kwh", "kwh_directo": "200", "distribuidora": "inexistente", "tarifa": "BT1"},
        )
        assert resp.status_code == 200

    def test_resultado_contiene_comparacion_distribuidoras(self, client):
        resp = self._post(client, kwh=250, distribuidora="enel")
        assert "Tu consumo en cada distribuidora" in resp.text

    def test_resultado_contiene_escenarios_ahorro(self, client):
        resp = self._post(client, kwh=250, distribuidora="enel")
        assert "ahorro" in resp.text.lower()

    def test_resultado_contiene_solar(self, client):
        resp = self._post(client, kwh=250, distribuidora="enel")
        assert "solar" in resp.text.lower()

    def test_comunas_resuelve_distribuidora(self, client):
        """Si se envía una comuna reconocida, se usa su distribuidora."""
        resp = client.post(
            "/calcular",
            data={"modo": "kwh", "kwh_directo": "200", "comuna": "Temuco", "tarifa": "BT1"},
        )
        assert resp.status_code == 200
        # Frontel debe aparecer en el resultado
        assert "Frontel" in resp.text


# ── GET /comunas ──────────────────────────────────────────────────────────────

class TestComunas:
    def test_get_200(self, client):
        resp = client.get("/comunas")
        assert resp.status_code == 200

    def test_muestra_las_cuatro_distribuidoras(self, client):
        resp = client.get("/comunas")
        for nombre in ["Enel", "CGE", "Chilquinta", "Frontel"]:
            assert nombre in resp.text

    def test_contiene_santiago(self, client):
        resp = client.get("/comunas")
        assert "Santiago" in resp.text

    def test_contiene_temuco(self, client):
        resp = client.get("/comunas")
        assert "Temuco" in resp.text

    def test_contiene_buscador(self, client):
        resp = client.get("/comunas")
        assert "buscar-comuna" in resp.text


# ── GET /api/gis/distribuidora ────────────────────────────────────────────────

class TestGisEndpoint:
    def test_coordenadas_invalidas_422(self, client):
        resp = client.get("/api/gis/distribuidora?lat=999&lon=0")
        assert resp.status_code == 422

    def test_falta_parametro_422(self, client):
        resp = client.get("/api/gis/distribuidora?lat=-33.4")
        assert resp.status_code == 422
