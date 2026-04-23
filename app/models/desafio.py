from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, Integer, String
from database import Base


class Desafio(Base):
    __tablename__ = "desafios"

    id            = Column(Integer, primary_key=True, index=True)
    nickname      = Column(String(50), nullable=True)
    kwh_anterior  = Column(Integer, nullable=False)
    kwh_actual    = Column(Integer, nullable=False)
    reduccion_pct = Column(Float, nullable=False)
    comuna        = Column(String(100), nullable=True)
    mes           = Column(String(7), nullable=False, index=True)   # "2026-04"
    fecha         = Column(DateTime, default=lambda: datetime.now(timezone.utc))
