from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from database import Base


class Tip(Base):
    __tablename__ = "tips"

    id              = Column(Integer, primary_key=True, index=True)
    texto           = Column(String(400), nullable=False)
    ahorro_estimado = Column(String(50), nullable=True)   # "$5.000/mes", "10%", etc.
    categoria       = Column(String(30), nullable=False, default="habitos")
    comuna          = Column(String(100), nullable=True)
    likes           = Column(Integer, default=0, nullable=False)
    aprobado        = Column(Boolean, default=True, nullable=False)
    fecha           = Column(DateTime, default=lambda: datetime.now(timezone.utc))
