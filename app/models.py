"""Ereignis- und Messwert-Schema (Projektanweisung 4.3).

Ereignisse: Orte, Zeiten, Themen. Keine Personen.
Messreihen (Pegel, Luft, Preise) gehen in eigene Tabellen und nicht ins Ereignisschema.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

EventType = Literal[
    "traffic", "congestion", "weather", "flood", "warning", "air", "radiation", "earthquake", "fire", "transit", "news", "social_signal", "aircraft"
]
Severity = Literal["info", "notice", "warning", "critical"]
SEVERITY_ORDER: dict[str, int] = {"info": 0, "notice": 1, "warning": 2, "critical": 3}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    """UTC-ISO-8601 mit Z. Naive Zeitstempel sind ein Fehler, keine Vermutung."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("Zeitstempel ohne Zeitzone")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Event(BaseModel):
    id: str
    source_id: str
    type: EventType
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=1200)
    severity: Severity = "info"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    geometry: dict[str, Any]
    region_tag: str = "DE-RLP"
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    fetched_at: datetime
    raw_ref: str | None = None
    ai_generated: bool = False
    model: str | None = None
    # Strukturierte Zusatzangaben fürs Frontend (Art, Verzögerung, Kurs …). Nie Kennungen oder Personen.
    attrs: dict[str, Any] = Field(default_factory=dict)

    @field_validator("valid_from", "valid_to", "fetched_at")
    @classmethod
    def _tz_required(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("Zeitzone fehlt")
        return v


class Station(BaseModel):
    source_id: str
    station_id: str
    name: str
    water: str | None = None
    km: float | None = None
    lat: float
    lon: float
    meta: dict[str, Any] = Field(default_factory=dict)


class Measurement(BaseModel):
    source_id: str
    station_id: str
    parameter: str
    ts: datetime
    value: float
    unit: str
    state: str | None = None  # z. B. PEGELONLINE stateMnwMhw

    @field_validator("ts")
    @classmethod
    def _tz_required(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Zeitzone fehlt")
        return v
