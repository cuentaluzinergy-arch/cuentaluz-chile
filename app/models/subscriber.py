import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, DateTime
from database import Base


def _new_token() -> str:
    return str(uuid.uuid4())


class Subscriber(Base):
    __tablename__ = "subscribers"

    id             = Column(Integer, primary_key=True, index=True)
    email          = Column(String, unique=True, index=True, nullable=False)
    fuente         = Column(String, default="calculadora")
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    token          = Column(String(36), unique=True, index=True, default=_new_token)
    activo         = Column(Boolean, default=True, nullable=False)
