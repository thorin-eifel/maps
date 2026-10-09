"""Collector-Pakete. Je Quelle ein Modul; Auswahl über das Feld `collector` im Quellenregister."""
from __future__ import annotations

import importlib

from .base import Collector, CollectResult, SourceError


def load_collector_class(name: str) -> type[Collector]:
    mod = importlib.import_module(f"app.collectors.{name}")
    cls = getattr(mod, "COLLECTOR", None)
    if cls is None:
        raise ImportError(f"Modul app.collectors.{name} definiert kein COLLECTOR")
    return cls


__all__ = ["Collector", "CollectResult", "SourceError", "load_collector_class"]
