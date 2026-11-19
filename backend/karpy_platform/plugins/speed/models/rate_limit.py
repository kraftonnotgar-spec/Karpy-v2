"""Database models for the Speed plugin."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, Integer, String, Text

from karpy_platform.core.base.models import BaseModel


class SpeedRateLimitRule(BaseModel):
    """Persistent rule metadata for future editable rate-limit profiles."""

    __tablename__ = "speed_rate_limit_rules"

    name = Column(String(120), nullable=False)
    rule_key = Column(String(120), nullable=False, unique=True, index=True)
    matcher = Column(String(500), nullable=False, default="*")
    scope = Column(String(40), nullable=False, default="ip")
    capacity = Column(Integer, nullable=False, default=120)
    refill_per_second = Column(Float, nullable=False, default=2.0)
    enabled = Column(Boolean, nullable=False, default=True)
    description = Column(Text, nullable=True)


class SpeedRateLimitEvent(BaseModel):
    """Audit table for persisted limiter events when durable logging is enabled."""

    __tablename__ = "speed_rate_limit_events"

    rule_key = Column(String(120), nullable=False, index=True)
    client_key = Column(String(255), nullable=False, index=True)
    method = Column(String(12), nullable=False)
    path = Column(String(600), nullable=False)
    status_code = Column(Integer, nullable=False, default=429)
    retry_after = Column(Integer, nullable=False, default=1)
    user_agent = Column(String(500), nullable=True)
    storage = Column(String(40), nullable=False, default="memory")
