"""Collector-Basisklasse.

Zweck:    Gemeinsame Regeln für jeden Collector (Projektanweisung 4.4):
          Timeout, Retry mit Backoff, Circuit Breaker, Logging, ehrlicher User-Agent,
          Geo-Filter am Rand, idempotentes Schreiben.
Aufruf:   Nicht direkt; über app.scheduler bzw. `python -m app.collect --once`.

Ein Collector implementiert nur `collect()` und liefert eine CollectResult.
`complete=False` heißt: der Abruf war unvollständig — es wird geschrieben,
aber nichts als „erledigt“ markiert.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from .. import geo
from ..config import Settings
from ..db import Storage
from ..models import Event, Measurement, Station, iso, utcnow
from ..registry import SourceEntry

log = logging.getLogger("osint.collector")


class SourceError(RuntimeError):
    """Fehler der Quelle (HTTP, Schema, Timeout) — führt zu Retry bzw. Fehlerlauf."""


@dataclass
class CollectResult:
    events: list[Event] = field(default_factory=list)
    stations: list[Station] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)
    cache: dict[str, Any] = field(default_factory=dict)
    complete: bool = True
    note: str | None = None  # z. B. „teilweise: Region X nicht erreichbar“
    writes_events: bool = True  # False bei reinen Messwert-Collectorn


class Collector(ABC):
    def __init__(
        self,
        entry: SourceEntry,
        storage: Storage,
        client: httpx.AsyncClient,
        settings: Settings,
        backoff_base_s: float = 1.0,
    ) -> None:
        self.entry = entry
        self.storage = storage
        self.client = client
        self.settings = settings
        self.backoff_base_s = backoff_base_s
        self.log = logging.getLogger(f"osint.collector.{entry.id}")

    # ------------------------------------------------------------ zu implementieren
    @abstractmethod
    async def collect(self) -> CollectResult: ...

    # ------------------------------------------------------------------ HTTP
    async def _request(self, url: str, params: dict[str, Any] | None, accept: str, allow_empty: bool,
                       secrets: tuple[str, ...], timeout: float | None = None) -> httpx.Response | None:
        """GET mit Retry (5xx, 429, Timeout, Transportfehler). 4xx sonst sofort Fehler.

        secrets: Werte (API-Schlüssel), die in Fehlertexten und Logs durch *** ersetzt werden; manche Dienste
        verlangen den Schlüssel im Pfad, dann stünde er sonst in status.json."""
        def hide(text: str) -> str:
            for sec in secrets:
                if sec:
                    text = text.replace(sec, "***")
            return text

        last: Exception | None = None
        delay: float | None = None
        for attempt in range(1, self.settings.http_max_attempts + 1):
            try:
                resp = await self.client.get(
                    url,
                    params=params,
                    headers={"User-Agent": self.settings.user_agent, "Accept": accept},
                    timeout=timeout or self.settings.http_timeout_s,
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    retry_after = resp.headers.get("Retry-After")
                    delay = min(float(retry_after), 60.0) if retry_after and retry_after.isdigit() else None
                    raise _Retryable(f"HTTP {resp.status_code}", delay)
                if resp.status_code >= 400:
                    raise SourceError(hide(f"HTTP {resp.status_code} von {url}"))
                if allow_empty and resp.status_code == 204:
                    return None
                return resp
            except _Retryable as exc:
                last = exc
                delay = exc.delay
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                delay = None
            if attempt < self.settings.http_max_attempts:
                wait = delay if delay is not None else self.backoff_base_s * (2 ** (attempt - 1))
                wait += random.uniform(0, self.backoff_base_s * 0.25)
                self.log.warning("Versuch %d/%d fehlgeschlagen (%s), warte %.1fs",
                                 attempt, self.settings.http_max_attempts, hide(str(last)), wait)
                await asyncio.sleep(wait)
        raise SourceError(hide(f"{url}: {type(last).__name__}: {last}")) from last

    async def fetch_json(self, url: str, params: dict[str, Any] | None = None, allow_empty: bool = False) -> Any:
        """JSON holen. allow_empty: HTTP 204 (kein Inhalt, z. B. FDSN ohne Treffer) ergibt None statt Fehler."""
        resp = await self._request(url, params, "application/json", allow_empty, ())
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise SourceError(f"Kein gültiges JSON von {url}") from exc

    async def fetch_bytes(self, url: str, params: dict[str, Any] | None = None, timeout: float = 120.0) -> bytes:
        """Binärdatei (ZIP, Protobuf) holen, gleiche Retry-Regeln, großzügigeres Zeitlimit."""
        resp = await self._request(url, params, "*/*", False, (), timeout)
        for _ in range(3):   # der Client folgt Weiterleitungen nicht von selbst; hier nur nach https
            assert resp is not None
            target = resp.headers.get("location")
            if resp.status_code not in (301, 302, 303, 307, 308) or not target:
                break
            target = str(resp.url.join(target))
            if not target.startswith("https://"):
                raise SourceError(f"Weiterleitung auf {target.split(':')[0]} abgelehnt")
            resp = await self._request(target, None, "*/*", False, (), timeout)
        assert resp is not None
        if resp.status_code != 200:
            raise SourceError(f"HTTP {resp.status_code} von {url}")
        return resp.content

    async def fetch_text(self, url: str, params: dict[str, Any] | None = None, secrets: tuple[str, ...] = ()) -> str:
        """Text (z. B. CSV) holen, gleiche Retry-Regeln. Schlüssel in `secrets` erscheinen nie in Meldungen."""
        resp = await self._request(url, params, "text/csv, text/plain, */*", False, secrets)
        assert resp is not None
        return resp.text

    # -------------------------------------------------------------- Geo am Rand
    @staticmethod
    def keep(geometry: dict[str, Any]) -> bool:
        try:
            return geo.geometry_within_radius(geometry)
        except (ValueError, KeyError, TypeError, IndexError):
            return False

    # ---------------------------------------------------------------------- Lauf
    async def run_once(self) -> bool:
        """Ein Lauf inklusive Circuit Breaker, Persistenz und Protokoll. Rückgabe: Erfolg."""
        sid = self.entry.id
        state = await asyncio.to_thread(self.storage.get_state, sid)
        open_until = state.get("open_until")
        if open_until and open_until > iso(utcnow()):
            self.log.warning("Circuit offen bis %s, Lauf übersprungen", open_until)
            return False

        started: datetime = utcnow()
        t0 = time.monotonic()
        try:
            result = await self.collect()
            n_new = n_seen = 0
            if result.stations:
                await asyncio.to_thread(self.storage.upsert_stations, result.stations)
            if result.measurements:
                n_new += await asyncio.to_thread(self.storage.add_measurements, result.measurements)
                n_seen += len(result.measurements)
            for key, payload in result.cache.items():
                await asyncio.to_thread(self.storage.cache_put, key, sid, payload)
            if result.writes_events:
                ev_new, ev_seen = await asyncio.to_thread(
                    self.storage.replace_snapshot, sid, result.events, result.complete
                )
                n_new += ev_new
                n_seen += ev_seen
            ms = int((time.monotonic() - t0) * 1000)
            await asyncio.to_thread(
                self.storage.record_run, sid, started, ms, True, n_new, n_seen, result.note,
                self.settings.breaker_threshold, self.settings.breaker_cooldown_s,
            )
            self.log.info("ok: %d neu, %d gesehen, %d ms%s", n_new, n_seen, ms,
                          f" ({result.note})" if result.note else "")
            return True
        except Exception as exc:  # noqa: BLE001 — ein Collector darf nie die App umwerfen
            ms = int((time.monotonic() - t0) * 1000)
            msg = f"{type(exc).__name__}: {exc}"
            self.log.error("Fehler nach %d ms: %s", ms, msg)
            await asyncio.to_thread(
                self.storage.record_run, sid, started, ms, False, 0, 0, msg,
                self.settings.breaker_threshold, self.settings.breaker_cooldown_s,
            )
            return False


class _Retryable(Exception):
    def __init__(self, msg: str, delay: float | None = None) -> None:
        super().__init__(msg)
        self.delay = delay
