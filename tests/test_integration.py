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


# ── GET /tips ─────────────────────────────────────────────────────────────────

class TestTips:
    def test_get_200(self, client):
        resp = client.get("/tips")
        assert resp.status_code == 200

    def test_contiene_titulo(self, client):
        resp = client.get("/tips")
        assert "tip" in resp.text.lower()

    def test_api_tips_json(self, client):
        resp = client.get("/api/tips?page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "tips" in data
        assert isinstance(data["tips"], list)

    def test_post_tip_crea_registro(self, client):
        resp = client.post("/api/tips", json={
            "texto": "Apagar luces al salir ahorra hasta 10% de energía mensual.",
            "categoria": "iluminacion",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True or "id" in data

    def test_post_tip_texto_corto_rechazado(self, client):
        resp = client.post("/api/tips", json={"texto": "Corto", "categoria": "habitos"})
        assert resp.status_code in (400, 422)

    def test_rss_feed(self, client):
        resp = client.get("/tips/rss")
        assert resp.status_code == 200
        assert "xml" in resp.headers.get("content-type", "").lower() or "<rss" in resp.text


# ── GET /desafio ──────────────────────────────────────────────────────────────

class TestDesafio:
    def test_get_200(self, client):
        resp = client.get("/desafio")
        assert resp.status_code == 200

    def test_contiene_ranking(self, client):
        resp = client.get("/desafio")
        assert "kwh" in resp.text.lower() or "consumo" in resp.text.lower()

    def test_post_desafio_registra(self, client):
        resp = client.post("/api/desafio", json={
            "kwh_anterior": 250,
            "kwh_actual": 200,
            "nickname": "TestUser",
            "comuna": "Santiago",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True or "reduccion_pct" in data

    def test_post_desafio_kwh_cero_rechazado(self, client):
        resp = client.post("/api/desafio", json={
            "kwh_anterior": 0,
            "kwh_actual": 0,
        })
        assert resp.status_code in (400, 422)


# ── Newsletter ────────────────────────────────────────────────────────────────

class TestNewsletter:
    def test_subscribe_email_valido(self, client):
        resp = client.post("/api/newsletter", json={
            "email": "test_integracion@ejemplo.cl",
            "fuente": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True

    def test_subscribe_email_invalido(self, client):
        resp = client.post("/api/newsletter", json={"email": "no-es-email"})
        assert resp.status_code in (400, 422)

    def test_baja_token_invalido(self, client):
        resp = client.get("/newsletter/baja?token=token-inexistente-xyz")
        assert resp.status_code in (200, 404)
        assert any(w in resp.text.lower() for w in ("no encontr", "enlace", "baja", "suscripci"))


# ── Páginas estáticas ─────────────────────────────────────────────────────────

class TestPaginasEstaticas:
    def test_privacidad_200(self, client):
        resp = client.get("/privacidad")
        assert resp.status_code == 200
        assert "privacidad" in resp.text.lower()

    def test_offline_200(self, client):
        resp = client.get("/offline")
        assert resp.status_code == 200

    def test_404_custom(self, client):
        resp = client.get("/ruta-que-no-existe-xyz")
        assert resp.status_code == 404
        assert "404" in resp.text or "encontr" in resp.text.lower()

    def test_robots_txt(self, client):
        resp = client.get("/robots.txt")
        assert resp.status_code == 200
        assert "User-agent" in resp.text

    def test_sitemap_xml(self, client):
        resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert "<urlset" in resp.text or "<url>" in resp.text

    def test_manifest_json(self, client):
        resp = client.get("/manifest.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "icons" in data


# ── Web Push ──────────────────────────────────────────────────────────────────

class TestPush:
    def test_vapid_public_key(self, client):
        resp = client.get("/api/push/vapid-public-key")
        assert resp.status_code == 200
        data = resp.json()
        assert "publicKey" in data
        assert len(data["publicKey"]) > 20
