"""Models for the KARPy Location plugin."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from karpy_platform.core.base.models import BaseModel


class Country(BaseModel):
    __tablename__ = "location_countries"
    __table_args__ = (
        Index("idx_location_countries_status_order", "status", "order"),
        Index("idx_location_countries_code_status", "code", "status"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    abbreviation: Mapped[str | None] = mapped_column(String(10), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(120), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="published", nullable=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    states: Mapped[list["State"]] = relationship("State", back_populates="country", lazy="selectin")
    cities: Mapped[list["City"]] = relationship("City", back_populates="country", lazy="selectin")


class State(BaseModel):
    __tablename__ = "location_states"
    __table_args__ = (
        Index("idx_location_states_country_status", "country_id", "status"),
        Index("idx_location_states_name_country", "name", "country_id"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    abbreviation: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country_id: Mapped[str] = mapped_column(String(36), ForeignKey("location_countries.id"), nullable=False, index=True)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="published", nullable=False, index=True)

    country: Mapped[Country] = relationship("Country", back_populates="states", lazy="selectin")
    cities: Mapped[list["City"]] = relationship("City", back_populates="state", lazy="selectin")


class City(BaseModel):
    __tablename__ = "location_cities"
    __table_args__ = (
        Index("idx_location_cities_country_state_status", "country_id", "state_id", "status"),
        Index("idx_location_cities_name_state", "name", "state_id"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    zip_code: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    country_id: Mapped[str] = mapped_column(String(36), ForeignKey("location_countries.id"), nullable=False, index=True)
    state_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("location_states.id"), nullable=True, index=True)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="published", nullable=False, index=True)

    country: Mapped[Country] = relationship("Country", back_populates="cities", lazy="selectin")
    state: Mapped[State | None] = relationship("State", back_populates="cities", lazy="selectin")

