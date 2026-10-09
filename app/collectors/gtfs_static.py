"""Fahrplan-Stammdaten (GTFS) für Luxemburg und den deutschen Regionalverkehr, zugeschnitten auf den Radius.

Quellen:    Luxemburg: data.public.lu, Datensatz "horaires-et-arrets-des-transport-publics-gtfs" (CC BY 4.0, wöchentlich neu)
            Deutschland Regionalverkehr: https://download.gtfs.de/germany/rv_free/latest.zip (CC BY 4.0, Quelle DELFI e. V.)
Betreiber:  Ministère de la Mobilité (LU) bzw. DELFI e. V. über gtfs.de
Intervall:  einmal je Woche (604800 s); die ZIP-Dateien werden nur ausgewertet, nicht aufbewahrt
Ablage:     Cache-Eintrag "gtfs_index" in der Datenbank: Haltestellen im Radius mit Verkehrsart und, für Feeds mit
            Echtzeit, die Fahrten (Linie, Ziel), die dort halten. Grundlage für gtfs_rt_de und die Bahnhofsebene.
Beispiel:   python -m app.collect --once --only gtfs_static

Der deutsche Nahverkehr (Busse, 287 MB) ist bewusst nicht dabei; er lässt sich über params.feeds ergänzen.
Fällt ein Feed aus, bleibt sein letzter Stand im Index; nur wenn alle ausfallen, gilt der Lauf als Fehler.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .. import gtfs
from ..models import iso, utcnow
from .base import Collector, CollectResult, SourceError

DEFAULT_FEEDS = [
    {"id": "lu", "kind": "datapublic", "dataset": "horaires-et-arrets-des-transport-publics-gtfs", "realtime": False, "region": "LU"},
    {"id": "de_rv", "kind": "url", "url": "https://download.gtfs.de/germany/rv_free/latest.zip", "realtime": True, "region": "DE"},
]
API = "https://data.public.lu/api/1/datasets/{dataset}/"


class GtfsStaticCollector(Collector):
    async def _zip_url(self, feed: dict[str, Any]) -> str:
        if feed["kind"] == "url":
            return feed["url"]
        d = await self.fetch_json(API.format(dataset=feed["dataset"]))
        res = [r for r in (d.get("resources") if isinstance(d, dict) else None) or [] if str(r.get("format", "")).lower() == "zip" and r.get("url")]
        if not res:
            raise SourceError("data.public.lu: keine ZIP-Ressource im Datensatz")
        res.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return res[0]["url"]

    async def collect(self) -> CollectResult:
        feeds = self.entry.params.get("feeds") or DEFAULT_FEEDS
        old = (self.storage.cache_get("gtfs_index") or {}).get("payload", {}).get("feeds", {})
        out: dict[str, Any] = dict(old)
        failed: list[str] = []
        first_err = ""
        for feed in feeds:
            try:
                url = await self._zip_url(feed)
                blob = await self.fetch_bytes(url, timeout=240.0)
                idx = await asyncio.to_thread(gtfs.build_index, blob, bool(feed.get("realtime")))
                idx.update(fetched_at=iso(utcnow()), source_url=url, region=feed.get("region", ""))
                out[feed["id"]] = idx
                self.log.info("%s: %d Haltestellen im Radius, %d Fahrten", feed["id"], len(idx["stops"]), idx["trip_count"])
            except (SourceError, ValueError, OSError) as exc:
                failed.append(feed["id"])
                first_err = first_err or f"{type(exc).__name__}: {exc}"
                self.log.warning("%s: %s", feed["id"], exc)
        if len(failed) == len(feeds):
            raise SourceError(f"GTFS: kein Feed lieferbar ({first_err})")
        note = f"teilweise: {', '.join(failed)} fehlgeschlagen, letzter Stand bleibt" if failed else None
        return CollectResult(cache={"gtfs_index": {"feeds": out}}, complete=not failed, note=note, writes_events=False)


COLLECTOR = GtfsStaticCollector
