from datetime import date
from sqlalchemy import Column, Integer, String, Date
from database import Base


class SecCache(Base):
    """
    Cache de resoluciones comuna → distribuidora.
    TTL: 180 días (las concesiones cambian muy poco).
    """
    __tablename__ = "sec_cache"

    id                 = Column(Integer, primary_key=True, index=True)
    comuna_normalizada = Column(String, unique=True, index=True, nullable=False)
    distribuidora_id   = Column(String, nullable=False)
    fecha_consulta     = Column(Date, nullable=False, default=date.today)
    fuente             = Column(String, nullable=False, default="nominatim")
