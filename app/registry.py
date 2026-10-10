"""Quellenregister: lädt und validiert sources.yaml.

Regel: Ohne Eintrag im Register läuft kein Collector.
Das Register ist zugleich die Grundlage der Seite „Quellen und Lizenzen“.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class ZugangField(BaseModel):
    """Ein Zugangsdatum einer Quelle (Schlüssel, Benutzername, Passwort). `env` ist der Name der Umgebungsvariable, die der Collector liest."""
    env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    art: Literal["schluessel", "benutzername", "passwort"] = "schluessel"
    bezeichnung: str


class SourceEntry(BaseModel):
    id: str
    name: str
    betreiber: str
    kurzname: str = Field(default="", description="Kurzform für Listen; leer = name")
    url: str
    lizenz: str
    lizenz_geprueft: bool = False
    lizenz_hinweis: str = ""
    namensnennung: str
    intervall: int = Field(gt=0, description="Sekunden zwischen zwei Abrufen")
    ratenlimit: str
    auth: str = "keine"
    zugang: list[ZugangField] = Field(default_factory=list, description="Zugangsdaten, die die Quelle braucht; die Desktop-App legt sie je Quelle lokal ab")
    geo_bezug: str
    datenschutz_risiko: Literal["niedrig", "mittel", "hoch"]
    aktiv: bool = True
    nutzung: Literal["offen", "privat"] = Field(
        default="offen", description="privat: Lizenz oder Bedingungen erlauben nur private, nicht-kommerzielle Nutzung; läuft nur mit OSINT_MODE=privat")
    zuletzt_geprüft: str
    erstlauf: Literal["sofort", "spaeter"] = Field(
        default="sofort", description="spaeter: braucht lange (große Abfragen). Die Desktop-App holt sie erst nach dem ersten Export im Hintergrund")
    collector: str
    params: dict[str, Any] = Field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        """Felder für die öffentliche Quellenseite (ohne interne Parameter)."""
        d = self.model_dump(exclude={"params", "zugang"})
        return d


class Registry:
    def __init__(self, entries: list[SourceEntry]) -> None:
        ids = [e.id for e in entries]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"Doppelte Quellen-IDs im Register: {sorted(dupes)}")
        self.entries = entries
        self._by_id = {e.id: e for e in entries}

    @classmethod
    def load(cls, path: Path) -> "Registry":
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict) or "sources" not in raw:
            raise ValueError(f"{path}: Schlüssel 'sources' fehlt")
        entries = [SourceEntry(**item) for item in raw["sources"]]
        envs = [f.env for e in entries for f in e.zugang]
        dupes = {x for x in envs if envs.count(x) > 1}
        if dupes:
            raise ValueError(f"Zugangsvariable bei mehreren Quellen: {sorted(dupes)}")
        if os.environ.get("OSINT_MODE", "oeffentlich").strip().lower() != "privat":
            entries = [e for e in entries if e.nutzung != "privat"]   # im öffentlichen Betrieb gibt es diese Quellen weder als Collector noch auf der Quellenseite
        return cls(entries)

    def get(self, source_id: str) -> SourceEntry:
        return self._by_id[source_id]

    def active(self) -> list[SourceEntry]:
        return [e for e in self.entries if e.aktiv]
