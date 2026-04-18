"""
Lógica de negocio de la calculadora — modelo de componentes real.

Estructura real de la boleta residencial chilena (BT1, Decreto CNE):

  Cargo fijo mensual                  → aplica IVA 19 %
  Cargo por servicio público (FET)    → EXENTO de IVA
  Cargos de transporte (troncal+zonal)→ aplica IVA 19 %
  Cargo por energía (precio nudo)     → aplica IVA 19 %
  Cargo por potencia / VAD            → aplica IVA 19 %
  Recargo FET (por tramo de consumo)  → aplica IVA 19 %  [BT1 ≤350 kWh = 0]
  ─────────────────────────────────────────────────────
  Subtotal IVA-afecto                 × 1.19
  + servicio público (exento)
  = TOTAL boleta

Referencias:
  Enel: Decreto 24T/2025 + VAD 5T/2024, vigente 01-04-2026.
  Otras distribuidoras: estimaciones sobre estructura CNE.
"""

import json
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent.parent / "config"

IVA = 0.19


# ──────────────────────────────────────────────────
# Carga de configuración
# ──────────────────────────────────────────────────

def cargar_tarifas() -> dict:
    with open(_BASE / "tarifas.json", encoding="utf-8") as f:
        return json.load(f)


def cargar_aparatos() -> dict:
    with open(_BASE / "aparatos.json", encoding="utf-8") as f:
        return json.load(f)


def cargar_comunas() -> list:
    with open(_BASE / "comunas_map.json", encoding="utf-8") as f:
        data = json.load(f)
    return data["comunas"]


def resolver_distribuidora(nombre_comuna: str) -> str | None:
    """Devuelve el distribuidora_id para una comuna (búsqueda tolerante a tildes/mayúsculas)."""
    import unicodedata
    def normalizar(s: str) -> str:
        return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()

    target = normalizar(nombre_comuna.strip())
    for c in cargar_comunas():
        if normalizar(c["nombre"]) == target or c["slug"] == target.replace(" ", "-"):
            return c["distribuidora_id"]
    return None


# ──────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────

def _recargo_fet(kwh: float, fet_recargos: list) -> float:
    """Calcula el recargo FET acumulado sobre los kWh en cada tramo."""
    recargo_total = 0.0
    for tramo in fet_recargos:
        t_desde = tramo["desde_kwh"]
        t_hasta = tramo["hasta_kwh"]
        recargo = tramo["recargo_kwh"]
        if kwh <= t_desde or recargo == 0:
            continue
        kwh_en_tramo = min(kwh, t_hasta) - t_desde
        recargo_total += kwh_en_tramo * recargo
    return recargo_total


def _componentes_bt1(kwh: float, tarifa: dict) -> dict:
    """Desglosa los componentes neto de una tarifa BT1 volumétrica."""
    fijo_neto    = tarifa["cargo_fijo_neto"]
    serv_pub     = tarifa["cargo_servicio_publico_kwh"] * kwh   # sin IVA
    transporte   = tarifa["cargo_transporte_kwh_neto"] * kwh
    energia      = tarifa["cargo_energia_kwh_neto"] * kwh
    potencia     = tarifa["cargo_potencia_kwh_neto"] * kwh
    fet_recargo  = _recargo_fet(kwh, tarifa.get("fet_recargos", []))

    afecto_iva   = fijo_neto + transporte + energia + potencia + fet_recargo
    iva          = afecto_iva * IVA
    total        = afecto_iva + iva + serv_pub

    return {
        "fijo_neto": fijo_neto, "serv_pub": serv_pub,
        "transporte": transporte, "energia": energia,
        "potencia": potencia, "fet_recargo": fet_recargo,
        "afecto_iva": afecto_iva, "iva": iva, "total": total,
    }


# ──────────────────────────────────────────────────
# Cálculo principal de boleta
# ──────────────────────────────────────────────────

def calcular_boleta(
    kwh: float,
    distribuidora: str,
    tarifa_tipo: str,
    demanda_punta_kw: float = 1.5,
) -> dict:
    """
    Calcula el desglose completo de la boleta mensual.

    Para BT1 (volumétrica): demanda_punta_kw se ignora.
    Para BT2 (por demanda):  demanda_punta_kw = potencia máxima en hora punta (kW).
        Valor por defecto 1.5 kW = estimación conservadora hogar pequeño.
    """
    tarifas_all  = cargar_tarifas()
    dist_data    = tarifas_all[distribuidora]
    tarifa       = dist_data["tarifas"][tarifa_tipo]
    verificado   = dist_data.get("datos_verificados", False)

    if tarifa_tipo == "BT1":
        comp = _componentes_bt1(kwh, tarifa)
    else:
        # BT2: energía al mismo precio nodo, pero potencia por demanda medida
        fijo_neto   = tarifa["cargo_fijo_neto"]
        serv_pub    = tarifa["cargo_servicio_publico_kwh"] * kwh
        transporte  = tarifa["cargo_transporte_kwh_neto"] * kwh
        energia     = tarifa["cargo_energia_kwh_neto"] * kwh
        potencia    = tarifa["cargo_demanda_punta_kw_mes_neto"] * demanda_punta_kw
        afecto_iva  = fijo_neto + transporte + energia + potencia
        iva         = afecto_iva * IVA
        total       = afecto_iva + iva + serv_pub
        comp = {
            "fijo_neto": fijo_neto, "serv_pub": serv_pub,
            "transporte": transporte, "energia": energia,
            "potencia": potencia, "fet_recargo": 0.0,
            "afecto_iva": afecto_iva, "iva": iva, "total": total,
        }

    total    = comp["total"]
    safe_tot = total if total > 0 else 1

    grupo_fijo    = comp["fijo_neto"] * (1 + IVA)
    grupo_energia = (comp["energia"] + comp["potencia"]) * (1 + IVA)
    grupo_transm  = comp["transporte"] * (1 + IVA)
    grupo_regulat = comp["serv_pub"] + comp["fet_recargo"] * (1 + IVA)

    return {
        "distribuidora_id":       distribuidora,
        "distribuidora":          dist_data["nombre"],
        "distribuidora_completo": dist_data["nombre_completo"],
        "tarifa_tipo":            tarifa_tipo,
        "tarifa_nombre":          tarifa["nombre"],
        "datos_verificados":      verificado,
        "vigente_desde":          dist_data.get("vigente_desde"),
        "ultima_actualizacion":   dist_data.get("ultima_actualizacion"),
        "kwh":                    round(kwh, 1),
        # Componentes con IVA incluido (lo que aparece en boleta)
        "cargo_fijo":             round(comp["fijo_neto"] * (1 + IVA)),
        "cargo_energia":          round(comp["energia"]   * (1 + IVA)),
        "cargo_potencia":         round(comp["potencia"]  * (1 + IVA)),
        "cargo_transporte":       round(comp["transporte"] * (1 + IVA)),
        "cargo_serv_publico":     round(comp["serv_pub"]),
        "cargo_fet_recargo":      round(comp["fet_recargo"] * (1 + IVA)),
        "iva":                    round(comp["iva"]),
        "subtotal_neto":          round(comp["afecto_iva"] + comp["serv_pub"]),
        "total":                  round(total),
        # Para gráfico de torta
        "grupo_fijo":    round(grupo_fijo),
        "grupo_energia": round(grupo_energia),
        "grupo_transm":  round(grupo_transm),
        "grupo_regulat": round(grupo_regulat),
        "pct_fijo":      round(grupo_fijo    / safe_tot * 100, 1),
        "pct_energia":   round(grupo_energia / safe_tot * 100, 1),
        "pct_transm":    round(grupo_transm  / safe_tot * 100, 1),
        "pct_regulat":   round(grupo_regulat / safe_tot * 100, 1),
    }


# ──────────────────────────────────────────────────
# Escenarios de ahorro
# ──────────────────────────────────────────────────

def calcular_escenarios(
    resultado: dict, distribuidora: str, tarifa_tipo: str
) -> list[dict]:
    """Impacto de reducir el consumo en 10 %, 20 % y 30 %."""
    escenarios = []
    for reduccion in [10, 20, 30]:
        nuevo_kwh  = resultado["kwh"] * (1 - reduccion / 100)
        nuevo      = calcular_boleta(nuevo_kwh, distribuidora, tarifa_tipo)
        ahorro_mes = resultado["total"] - nuevo["total"]
        escenarios.append({
            "reduccion":      reduccion,
            "nuevo_kwh":      round(nuevo_kwh, 1),
            "nuevo_total":    nuevo["total"],
            "ahorro_mensual": round(ahorro_mes),
            "ahorro_anual":   round(ahorro_mes * 12),
        })
    return escenarios


# ──────────────────────────────────────────────────
# Paneles solares
# ──────────────────────────────────────────────────

def calcular_solar(resultado: dict) -> dict:
    """
    Estimación simplificada de retorno de inversión solar fotovoltaico.
    Sistema 3 kWp, costo $2.5M–$4M CLP, generación ~350 kWh/mes (promedio nacional).
    """
    kwh        = resultado["kwh"]
    costo_min  = 2_500_000
    costo_max  = 4_000_000
    costo_mid  = 3_250_000
    produccion = 350

    precio_efect = (
        (resultado["cargo_energia"] + resultado["cargo_potencia"] + resultado["cargo_transporte"])
        / kwh
        if kwh > 0 else 0
    )

    kwh_aprovec  = min(kwh, produccion)
    ahorro_mes   = round(kwh_aprovec * precio_efect)
    ahorro_anual = ahorro_mes * 12
    payback      = round(costo_mid / ahorro_anual, 1) if ahorro_anual > 0 else None
    cobertura    = round(min(kwh_aprovec / kwh * 100, 100), 1) if kwh > 0 else 0

    return {
        "costo_min":          costo_min,
        "costo_max":          costo_max,
        "produccion_mensual": produccion,
        "kwh_aprovechable":   kwh_aprovec,
        "ahorro_mensual":     ahorro_mes,
        "ahorro_anual":       ahorro_anual,
        "payback_anos":       payback,
        "cobertura_pct":      cobertura,
        "conviene":           payback is not None and payback <= 8,
    }


# ──────────────────────────────────────────────────
# Comparación BT1 vs BT2
# ──────────────────────────────────────────────────

def _demanda_limite_bt2(kwh: float, distribuidora: str) -> float | None:
    """Bisección: demanda máxima (kW) a la que BT2 deja de ser conveniente."""
    bt1_total = calcular_boleta(kwh, distribuidora, "BT1")["total"]
    lo, hi = 0.1, 10.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if calcular_boleta(kwh, distribuidora, "BT2", demanda_punta_kw=mid)["total"] < bt1_total:
            lo = mid
        else:
            hi = mid
    limite = round((lo + hi) / 2, 2)
    return limite if limite < 9.5 else None


def calcular_comparacion_tarifas(kwh: float, distribuidora: str) -> dict:
    """
    Compara BT1 vs BT2 con distintos escenarios de demanda máxima en hora punta.

    La BT2 real en Chile cobra por DEMANDA MÁXIMA ($/kW/mes) en hora punta,
    no por energía consumida en ese horario.
    """
    bt1       = calcular_boleta(kwh, distribuidora, "BT1")
    bt2_baja  = calcular_boleta(kwh, distribuidora, "BT2", demanda_punta_kw=1.0)
    bt2_media = calcular_boleta(kwh, distribuidora, "BT2", demanda_punta_kw=2.0)
    bt2_alta  = calcular_boleta(kwh, distribuidora, "BT2", demanda_punta_kw=3.5)

    return {
        "bt1_total":          bt1["total"],
        "bt2_baja_total":     bt2_baja["total"],
        "bt2_media_total":    bt2_media["total"],
        "bt2_alta_total":     bt2_alta["total"],
        "diferencia_baja":    round(bt1["total"] - bt2_baja["total"]),
        "diferencia_media":   round(bt1["total"] - bt2_media["total"]),
        "diferencia_alta":    round(bt1["total"] - bt2_alta["total"]),
        "conviene_bt2_baja":  bt2_baja["total"]  < bt1["total"],
        "conviene_bt2_media": bt2_media["total"] < bt1["total"],
        "conviene_bt2_alta":  bt2_alta["total"]  < bt1["total"],
        "demanda_limite_kw":  _demanda_limite_bt2(kwh, distribuidora),
    }


# ──────────────────────────────────────────────────
# Comparación entre distribuidoras
# ──────────────────────────────────────────────────

def calcular_comparacion_distribuidoras(kwh: float, tarifa_tipo: str = "BT1") -> list[dict]:
    """
    Calcula la boleta para las 4 distribuidoras con el mismo kWh.
    Retorna lista ordenada de menor a mayor total, con el ahorro/costo
    relativo respecto a la distribuidora más barata.
    """
    tarifas = cargar_tarifas()
    resultados = []
    for dist_id, dist_data in tarifas.items():
        if not isinstance(dist_data, dict) or "tarifas" not in dist_data:
            continue
        if tarifa_tipo not in dist_data["tarifas"]:
            continue
        try:
            res = calcular_boleta(kwh, dist_id, tarifa_tipo)
            resultados.append({
                "distribuidora_id":  dist_id,
                "distribuidora":     res["distribuidora"],
                "region":            dist_data.get("region", ""),
                "total":             res["total"],
                "datos_verificados": res["datos_verificados"],
                "es_mas_barata":     False,
                "es_mas_cara":       False,
                "diff_vs_minimo":    0,
            })
        except Exception:
            pass

    if not resultados:
        return []

    resultados.sort(key=lambda r: r["total"])
    minimo = resultados[0]["total"]
    resultados[0]["es_mas_barata"] = True
    resultados[-1]["es_mas_cara"] = True
    for r in resultados:
        r["diff_vs_minimo"] = round(r["total"] - minimo)

    return resultados


# ──────────────────────────────────────────────────
# Recomendaciones personalizadas
# ──────────────────────────────────────────────────

def generar_recomendaciones(resultado: dict, distribuidora: str) -> list[dict]:
    kwh         = resultado["kwh"]
    tarifa_tipo = resultado.get("tarifa_tipo", "BT1")
    recs        = []

    if kwh >= 350:
        recs.append({
            "icono": "🌡️", "titulo": "Optimiza tu climatización",
            "texto": (
                f"Con {kwh:.0f} kWh/mes tu consumo es alto. El aire acondicionado "
                "y la calefacción eléctrica pueden representar hasta el 50 % de la boleta. "
                "Reducir 1-2 °C el termostato o mejorar el aislamiento baja 10-20 % el consumo."
            ),
            "ahorro_estimado": "10–20 %",
        })
    elif kwh >= 180:
        recs.append({
            "icono": "👕", "titulo": "Lava en frío, plancha concentrado",
            "texto": (
                "El ciclo caliente de la lavadora consume hasta 90 % más energía que el frío. "
                "Planchar una vez a la semana (todas las prendas juntas) evita recalentar "
                "el aparato en cada uso."
            ),
            "ahorro_estimado": "~5 %",
        })

    recs.append({
        "icono": "💡", "titulo": "Migra a iluminación LED completa",
        "texto": (
            "Las ampolletas LED consumen hasta 80 % menos que las halógenas y duran "
            "25 veces más. Si aún tienes fluorescentes o halógenas, el retorno de "
            "inversión en Chile es de menos de 6 meses."
        ),
        "ahorro_estimado": "3–8 %",
    })

    comp      = calcular_comparacion_tarifas(kwh, distribuidora)
    limite_kw = comp["demanda_limite_kw"]
    if tarifa_tipo == "BT1" and limite_kw is not None:
        recs.append({
            "icono": "📊", "titulo": "¿Te conviene la tarifa BT2?",
            "texto": (
                f"La BT2 cobra por tu demanda MÁXIMA en hora punta (18-23 h), no por "
                f"la energía consumida en ese horario. Si tu peak en ese horario no supera "
                f"los {limite_kw:.1f} kW (p.ej., solo tienes encendidos la TV y unas ampolletas), "
                "podría convenirte. Mide tu consumo punta antes de cambiar."
            ),
            "ahorro_estimado": "variable",
        })
    else:
        recs.append({
            "icono": "🔌", "titulo": "Elimina el consumo fantasma",
            "texto": (
                "Los aparatos en standby (TV, decodificador, microondas, cargadores) "
                "representan el 5–10 % de la boleta. Usa regletas con interruptor o "
                "desenchúfalos al salir. Es ahorro de costo cero."
            ),
            "ahorro_estimado": "5–10 %",
        })

    return recs[:3]
