"""
tests/test_scrapers.py

Ejecutar con:
    pytest tests/ -v
    pytest tests/ -v -k "test_enel"  # solo tests de Enel
"""
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def pdf_enel():
    """Path al PDF de Enel en la raiz del proyecto (requiere archivo presente)."""
    pdfs = list(_ROOT.glob("Enel*.pdf"))
    if not pdfs:
        pytest.skip("PDF de Enel no encontrado en raiz del proyecto")
    return pdfs[0]


@pytest.fixture
def tarifas_actuales():
    """Tarifas vigentes de config/tarifas.json."""
    with open(_ROOT / "config" / "tarifas.json", encoding="utf-8") as f:
        return json.load(f)


# ── Utilidades de base_scraper ─────────────────────────────────────────────────

class TestNormalizarNumero:
    def setup_method(self):
        from scrapers.base_scraper import BaseScraper
        self.norm = BaseScraper.normalizar_numero

    def test_coma_decimal_chileno(self):
        assert self.norm("596,176") == pytest.approx(596.176)

    def test_punto_decimal(self):
        assert self.norm("131.039") == pytest.approx(131.039)

    def test_formato_miles_coma_decimal(self):
        assert self.norm("1.234,56") == pytest.approx(1234.56)

    def test_con_signo_pesos(self):
        assert self.norm("$ 596,176") == pytest.approx(596.176)

    def test_cero(self):
        assert self.norm("0,000") == pytest.approx(0.0)

    def test_vacio(self):
        assert self.norm("") is None

    def test_texto_no_numerico(self):
        assert self.norm("N/A") is None

    def test_negativo_rechazado(self):
        assert self.norm("-5,5") is None


# ── detectar_cambios ──────────────────────────────────────────────────────────

class TestDetectarCambios:
    def setup_method(self):
        from scrapers.base_scraper import BaseScraper
        s = BaseScraper()
        s.DISTRIBUIDORA_ID = "test"
        self.scraper = s

    def _bt1(self, energia=131.0, fijo=596.0):
        return {"BT1": {"cargo_energia_kwh_neto": energia, "cargo_fijo_neto": fijo}}

    def test_sin_cambios(self):
        assert self.scraper.detectar_cambios(self._bt1(), self._bt1()) is False

    def test_cambio_energia(self):
        assert self.scraper.detectar_cambios(self._bt1(energia=140.0), self._bt1(energia=131.0)) is True

    def test_cambio_menor_al_umbral(self):
        # Diferencia de 0.1 < umbral de 0.5 → no es cambio
        assert self.scraper.detectar_cambios(self._bt1(energia=131.1), self._bt1(energia=131.0)) is False

    def test_campo_faltante_en_nuevas(self):
        # Campo ausente en nuevas → no se compara → no es cambio
        nuevas = {"BT1": {"cargo_fijo_neto": 596.0}}
        assert self.scraper.detectar_cambios(nuevas, self._bt1()) is False


# ── validar_tarifas ───────────────────────────────────────────────────────────

class TestValidarTarifas:
    def setup_method(self):
        from scrapers.base_scraper import BaseScraper
        s = BaseScraper()
        s.DISTRIBUIDORA_ID = "test"
        self.scraper = s

    def _tarifas(self, energia=131.0, fijo=596.0):
        return {"BT1": {
            "cargo_energia_kwh_neto": energia,
            "cargo_fijo_neto": fijo,
        }}

    def test_validas(self):
        assert self.scraper.validar_tarifas(self._tarifas(), self._tarifas()) is True

    def test_energia_cero_rechazada(self):
        assert self.scraper.validar_tarifas(self._tarifas(energia=0), self._tarifas()) is False

    def test_variacion_mayor_50_pct_rechazada(self):
        # 200 vs 131 = 53% de diferencia → rechazar
        assert self.scraper.validar_tarifas(self._tarifas(energia=200.0), self._tarifas(energia=131.0)) is False

    def test_variacion_menor_50_pct_aceptada(self):
        # 145 vs 131 = 11% → aceptar
        assert self.scraper.validar_tarifas(self._tarifas(energia=145.0), self._tarifas(energia=131.0)) is True

    def test_fijo_cero_rechazado(self):
        assert self.scraper.validar_tarifas(self._tarifas(fijo=0), self._tarifas()) is False


# ── Mapeo comuna → distribuidora ──────────────────────────────────────────────

class TestMapeoComunas:
    def setup_method(self):
        from services.tarifa_service import get_distribuidora
        self.get = get_distribuidora

    CASOS = [
        # (comuna, distribuidora_esperada)
        ("Santiago",        "enel"),
        ("Providencia",     "enel"),
        ("Las Condes",      "enel"),
        ("Maipú",           "enel"),
        ("Puente Alto",     "enel"),
        ("Vitacura",        "enel"),
        ("Tiltil",          "cge"),
        ("Curacaví",        "cge"),
        ("María Pinto",     "cge"),
        ("Valparaíso",      "chilquinta"),
        ("Viña del Mar",    "chilquinta"),
        ("Quilpué",         "chilquinta"),
        ("Los Andes",       "chilquinta"),
        ("Concepción",      "cge"),
        ("Talca",           "cge"),
        ("La Serena",       "cge"),
        ("Antofagasta",     "cge"),
        ("Temuco",          "frontel"),
        ("Villarrica",      "frontel"),
        ("Pucón",           "frontel"),
    ]

    @pytest.mark.parametrize("comuna, esperado", CASOS)
    def test_mapeo(self, comuna, esperado):
        resultado = self.get(comuna)
        assert resultado == esperado, f"{comuna}: esperado={esperado}, obtenido={resultado}"

    def test_comuna_inexistente(self):
        assert self.get("ComunaQueNoExiste") is None

    def test_tolerante_a_tildes(self):
        # "Maipu" sin tilde debe resolver igual que "Maipú"
        assert self.get("Maipu") == "enel"

    def test_tolerante_a_mayusculas(self):
        assert self.get("SANTIAGO") == "enel"
        assert self.get("santiago") == "enel"


# ── Calculo de boleta ─────────────────────────────────────────────────────────

class TestCalcularBoleta:
    """Verifica calculo con valores conocidos del Decreto 24T/2025 (Enel RM)."""

    def setup_method(self):
        from app.services.calculator_service import calcular_boleta
        self.calc = calcular_boleta

    def test_enel_bt1_250kwh(self):
        r = self.calc(250, "enel", "BT1")
        assert r["total"] == 51642, f"Esperado $51.642, obtenido ${r['total']}"

    def test_enel_bt1_350kwh_sin_recargo_fet(self):
        # Exactamente 350 kWh → sin recargo FET (tramo 0 = 0.000)
        r = self.calc(350, "enel", "BT1")
        assert r["cargo_fet_recargo"] == 0

    def test_enel_bt1_400kwh_con_recargo_fet(self):
        # 400 kWh → 50 kWh en tramo de recargo 0.923 → recargo > 0
        r = self.calc(400, "enel", "BT1")
        assert r["cargo_fet_recargo"] > 0

    def test_estructura_resultado(self):
        r = self.calc(200, "enel", "BT1")
        campos_requeridos = [
            "total", "cargo_fijo", "cargo_energia", "cargo_potencia",
            "cargo_transporte", "cargo_serv_publico", "iva",
            "grupo_fijo", "grupo_energia", "grupo_transm", "grupo_regulat",
            "pct_fijo", "pct_energia", "pct_transm", "pct_regulat",
        ]
        for campo in campos_requeridos:
            assert campo in r, f"Campo ausente en resultado: {campo}"

    def test_total_coherente_con_componentes(self):
        r = self.calc(300, "enel", "BT1")
        suma = r["grupo_fijo"] + r["grupo_energia"] + r["grupo_transm"] + r["grupo_regulat"]
        # Los grupos estan con IVA, el total tambien → deben ser iguales
        assert abs(suma - r["total"]) <= 2  # tolerancia de $2 por redondeos

    def test_pct_suma_100(self):
        r = self.calc(300, "enel", "BT1")
        suma_pct = r["pct_fijo"] + r["pct_energia"] + r["pct_transm"] + r["pct_regulat"]
        assert abs(suma_pct - 100.0) <= 0.5

    def test_enel_bt2_menor_demanda(self):
        # BT2 con demanda alta → debe ser mas caro que BT1
        bt1 = self.calc(250, "enel", "BT1")
        bt2 = self.calc(250, "enel", "BT2", demanda_punta_kw=3.5)
        assert bt2["total"] > bt1["total"]


# ── Metadata y vigencia ───────────────────────────────────────────────────────

class TestMetadata:
    def test_metadata_tiene_campos_requeridos(self):
        from services.tarifa_service import get_metadata
        meta = get_metadata()
        assert "ultima_actualizacion" in meta
        assert "dias_desde_actualizacion" in meta
        assert "alerta_desactualizado" in meta
        assert "proxima_actualizacion" in meta

    def test_alerta_false_si_reciente(self):
        """Con fecha de hoy, alerta debe ser False."""
        from services.tarifa_service import get_metadata
        import json
        from pathlib import Path
        # Simular tarifas con fecha de hoy
        from datetime import date
        tarifas_path = _ROOT / "config" / "tarifas.json"
        data = json.loads(tarifas_path.read_text(encoding="utf-8"))
        original = data["metadata"]["ultima_actualizacion"]
        data["metadata"]["ultima_actualizacion"] = date.today().isoformat()
        tarifas_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            meta = get_metadata()
            assert meta["alerta_desactualizado"] is False
        finally:
            data["metadata"]["ultima_actualizacion"] = original
            tarifas_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Parsing PDF de Enel (integration test) ────────────────────────────────────

class TestEnelScraperPDF:
    def test_parseo_pdf_extrae_valores(self, pdf_enel):
        from scrapers.enel_scraper import EnelScraper
        scraper = EnelScraper()
        filas   = scraper.parse_pdf(pdf_enel)
        assert len(filas) > 50, "PDF deberia tener mas de 50 filas en tablas"

    def test_extrae_cargo_fijo(self, pdf_enel):
        from scrapers.enel_scraper import EnelScraper
        scraper = EnelScraper()
        filas   = scraper.parse_pdf(pdf_enel)
        resultado = scraper.extraer_valores(filas)
        assert resultado is not None
        assert resultado["BT1"]["cargo_fijo_neto"] == pytest.approx(596.176, rel=0.01)

    def test_extrae_energia(self, pdf_enel):
        from scrapers.enel_scraper import EnelScraper
        scraper = EnelScraper()
        filas   = scraper.parse_pdf(pdf_enel)
        resultado = scraper.extraer_valores(filas)
        assert resultado["BT1"]["cargo_energia_kwh_neto"] == pytest.approx(131.039, rel=0.01)

    def test_extrae_transporte(self, pdf_enel):
        from scrapers.enel_scraper import EnelScraper
        scraper = EnelScraper()
        filas   = scraper.parse_pdf(pdf_enel)
        resultado = scraper.extraer_valores(filas)
        assert resultado["BT1"]["cargo_transporte_kwh_neto"] == pytest.approx(13.415, rel=0.01)

    def test_resultado_pasa_validacion(self, pdf_enel, tarifas_actuales):
        from scrapers.enel_scraper import EnelScraper
        from scrapers.base_scraper import BaseScraper
        scraper    = EnelScraper()
        validator  = BaseScraper()
        validator.DISTRIBUIDORA_ID = "enel"
        filas      = scraper.parse_pdf(pdf_enel)
        resultado  = scraper.extraer_valores(filas)
        actuales   = tarifas_actuales["enel"]["tarifas"]
        assert validator.validar_tarifas(resultado, actuales) is True
