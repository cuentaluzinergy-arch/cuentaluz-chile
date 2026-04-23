from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from database import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id         = Column(Integer, primary_key=True, index=True)
    endpoint   = Column(String, unique=True, nullable=False, index=True)
    p256dh     = Column(String, nullable=False)
    auth       = Column(String, nullable=False)
    user_agent = Column(String, nullable=True)
    fecha      = Column(DateTime, default=datetime.utcnow)
