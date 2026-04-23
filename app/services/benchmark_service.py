import statistics
from sqlalchemy.orm import Session
from app.models.benchmark import Benchmark

MIN_MUESTRA = 5   # mínimo de registros para mostrar el benchmark
MAX_KWH     = 5000


def guardar(db: Session, comuna: str, distribuidora_id: str, kwh: int) -> None:
    if not comuna or not (1 <= kwh <= MAX_KWH):
        return
    db.add(Benchmark(comuna=comuna.strip(), distribuidora_id=distribuidora_id, kwh=kwh))
    db.commit()


def stats_comuna(db: Session, comuna: str, kwh_usuario: int) -> dict | None:
    filas = db.query(Benchmark.kwh).filter(Benchmark.comuna == comuna.strip()).all()
    valores = [r.kwh for r in filas]
    n = len(valores)
    if n < MIN_MUESTRA:
        return None

    promedio = round(statistics.mean(valores))
    mediana  = round(statistics.median(valores))
    minimo   = min(valores)
    maximo   = max(valores)

    menores  = sum(1 for v in valores if v < kwh_usuario)
    percentil = round(menores / n * 100)

    diff_pct = round((kwh_usuario - promedio) / promedio * 100)

    # Posición relativa en la barra (0–100%) usando rango intercuartil extendido
    rango = max(maximo - minimo, 1)
    pos_pct = min(100, max(0, round((kwh_usuario - minimo) / rango * 100)))

    return {
        "n":              n,
        "promedio_kwh":   promedio,
        "mediana_kwh":    mediana,
        "minimo_kwh":     minimo,
        "maximo_kwh":     maximo,
        "percentil":      percentil,
        "diff_pct":       diff_pct,       # negativo = consume menos que promedio
        "pos_pct":        pos_pct,        # posición en barra visual 0–100
        "promedio_pos":   round((promedio - minimo) / rango * 100),
    }
