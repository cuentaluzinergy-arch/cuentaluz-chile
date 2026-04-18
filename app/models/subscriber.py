from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from database import Base


class Subscriber(Base):
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    fuente = Column(String, default="calculadora")
    fecha_registro = Column(DateTime, default=datetime.utcnow)
