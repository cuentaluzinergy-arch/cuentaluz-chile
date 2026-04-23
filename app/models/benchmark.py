from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, String
from database import Base


class Benchmark(Base):
    __tablename__ = "benchmark"

    id              = Column(Integer, primary_key=True, index=True)
    comuna          = Column(String(100), index=True, nullable=False)
    distribuidora_id = Column(String(20), nullable=False)
    kwh             = Column(Integer, nullable=False)
    fecha           = Column(DateTime, default=lambda: datetime.now(timezone.utc))
