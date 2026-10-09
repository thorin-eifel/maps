"""Speicher: SQLite (WAL). MVP-Entscheidung: kein Spatialite.

Zweck:    Ereignisse (Snapshot-Semantik je Quelle), Stationen, Messreihen,
          Collector-Läufe und -Zustand, kleiner Cache für Vorhersagen.
Warum kein Spatialite: Der Radiusfilter passiert am Rand im Collector (app.geo);
          die DB hält nur, was drin sein darf. PostGIS folgt in Phase 2, wenn die Mengen es verlangen.

Snapshot-Semantik: Ein Collector liefert jeweils die *vollständige* aktive Menge seiner Quelle.
          Was danach fehlt, wird inaktiv gesetzt — aber nur, wenn der Abruf vollständig war.
          Ein halber Abruf darf keine Meldungen löschen.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from . import geo
from .models import Event, Measurement, Station, iso, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL,
    type          TEXT NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    severity      TEXT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 1.0,
    geometry      TEXT NOT NULL,
    lat           REAL NOT NULL,
    lon           REAL NOT NULL,
    distance_km   REAL NOT NULL,
    region_tag    TEXT NOT NULL,
    valid_from    TEXT,
    valid_to      TEXT,
    fetched_at    TEXT NOT NULL,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    raw_ref       TEXT,
    ai_generated  INTEGER NOT NULL DEFAULT 0,
    model         TEXT,
    attrs         TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_active ON events(active, type, severity);
CREATE INDEX IF NOT EXISTS ix_events_source ON events(source_id, active);

CREATE TABLE IF NOT EXISTS stations (
    source_id  TEXT NOT NULL,
    station_id TEXT NOT NULL,
    name       TEXT NOT NULL,
    water      TEXT,
    km         REAL,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    distance_km REAL NOT NULL,
    meta       TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (source_id, station_id)
);

CREATE TABLE IF NOT EXISTS measurements (
    source_id  TEXT NOT NULL,
    station_id TEXT NOT NULL,
    parameter  TEXT NOT NULL,
    ts         TEXT NOT NULL,
    value      REAL NOT NULL,
    unit       TEXT NOT NULL,
    state      TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source_id, station_id, parameter, ts)
);

CREATE TABLE IF NOT EXISTS kv_cache (
    key        TEXT PRIMARY KEY,
    source_id  TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collector_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    ok          INTEGER NOT NULL,
    n_new       INTEGER NOT NULL DEFAULT 0,
    n_seen      INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_source ON collector_runs(source_id, id DESC);

CREATE TABLE IF NOT EXISTS collector_state (
    source_id            TEXT PRIMARY KEY,
    last_success         TEXT,
    last_attempt         TEXT,
    last_error           TEXT,
    failing_since        TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    open_until           TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Storage:
    """Dünne Schicht über sqlite3. Zugriffe sind über ein Lock serialisiert."""

    def __init__(self, path: Path, readonly: bool = False) -> None:
        self.path = Path(path)
        self.readonly = readonly
        self._lock = threading.RLock()
        if readonly:
            uri = f"file:{self.path}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=10)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _migrate(self) -> None:
        """Ältere Datenbanken nachziehen (idempotent)."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(events)")}
        if "attrs" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN attrs TEXT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ---------------------------------------------------------------- Ereignisse
    def replace_snapshot(
        self, source_id: str, events: Sequence[Event], complete: bool = True
    ) -> tuple[int, int]:
        """Schreibt Ereignisse idempotent. Rückgabe: (neu, gesehen)."""
        now = iso(utcnow())
        n_new = 0
        seen_ids: list[str] = []
        with self._tx() as c:
            for ev in events:
                lat, lon = geo.representative_point(ev.geometry)
                dist = geo.geometry_distance_km(ev.geometry)
                exists = c.execute("SELECT 1 FROM events WHERE id=?", (ev.id,)).fetchone()
                if not exists:
                    n_new += 1
                c.execute(
                    """INSERT INTO events (id, source_id, type, title, summary, severity, confidence,
                           geometry, lat, lon, distance_km, region_tag, valid_from, valid_to,
                           fetched_at, first_seen, last_seen, active, raw_ref, ai_generated, model, attrs)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                           title=excluded.title, summary=excluded.summary, severity=excluded.severity,
                           confidence=excluded.confidence, geometry=excluded.geometry,
                           lat=excluded.lat, lon=excluded.lon, distance_km=excluded.distance_km,
                           region_tag=excluded.region_tag, valid_from=excluded.valid_from,
                           valid_to=excluded.valid_to, fetched_at=excluded.fetched_at,
                           last_seen=excluded.last_seen, active=1, raw_ref=excluded.raw_ref,
                           ai_generated=excluded.ai_generated, model=excluded.model,
                           attrs=excluded.attrs""",
                    (
                        ev.id, ev.source_id, ev.type, ev.title, ev.summary, ev.severity, ev.confidence,
                        json.dumps(ev.geometry, separators=(",", ":")), lat, lon, round(dist, 2),
                        ev.region_tag, iso(ev.valid_from), iso(ev.valid_to), iso(ev.fetched_at),
                        now, now, ev.raw_ref, int(ev.ai_generated), ev.model,
                        json.dumps(ev.attrs, separators=(",", ":")) if ev.attrs else None,
                    ),
                )
                seen_ids.append(ev.id)
            if complete:
                if seen_ids:
                    marks = ",".join("?" * len(seen_ids))
                    c.execute(
                        f"UPDATE events SET active=0 WHERE source_id=? AND active=1 AND id NOT IN ({marks})",
                        (source_id, *seen_ids),
                    )
                else:
                    c.execute("UPDATE events SET active=0 WHERE source_id=? AND active=1", (source_id,))
            self._bump(c)
        return n_new, len(seen_ids)

    def active_events(
        self,
        types: Sequence[str] | None = None,
        min_severity: str | None = None,
        within_hours: int | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events WHERE active=1"
        params: list[Any] = []
        if types:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            params += list(types)
        if min_severity:
            order = {"info": 0, "notice": 1, "warning": 2, "critical": 3}
            allowed = [s for s, o in order.items() if o >= order[min_severity]]
            sql += f" AND severity IN ({','.join('?' * len(allowed))})"
            params += allowed
        if within_hours is not None:
            # relevant, wenn jetzt gültig oder innerhalb des Fensters beginnend
            now = utcnow()
            sql += " AND COALESCE(valid_to, '9999') >= ? AND COALESCE(valid_from, first_seen) <= ?"
            params += [iso(now), iso(now + timedelta(hours=within_hours))]
        sql += " ORDER BY CASE severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 WHEN 'notice' THEN 1 ELSE 0 END DESC, distance_km ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._query(sql, params)]

    def count_active(self, source_id: str) -> int:
        return self._query("SELECT COUNT(*) n FROM events WHERE source_id=? AND active=1", (source_id,))[0]["n"]

    # --------------------------------------------------------- Stationen / Messwerte
    def upsert_stations(self, stations: Sequence[Station]) -> None:
        with self._tx() as c:
            for s in stations:
                dist = geo.haversine_km(geo.config.CENTER_LAT, geo.config.CENTER_LON, s.lat, s.lon)
                c.execute(
                    """INSERT INTO stations (source_id, station_id, name, water, km, lat, lon, distance_km, meta)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(source_id, station_id) DO UPDATE SET
                         name=excluded.name, water=excluded.water, km=excluded.km, lat=excluded.lat,
                         lon=excluded.lon, distance_km=excluded.distance_km, meta=excluded.meta""",
                    (s.source_id, s.station_id, s.name, s.water, s.km, s.lat, s.lon, round(dist, 2),
                     json.dumps(s.meta, separators=(",", ":"))),
                )
            self._bump(c)

    def add_measurements(self, rows: Sequence[Measurement]) -> int:
        now = iso(utcnow())
        n = 0
        with self._tx() as c:
            for m in rows:
                cur = c.execute(
                    """INSERT OR IGNORE INTO measurements
                       (source_id, station_id, parameter, ts, value, unit, state, fetched_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (m.source_id, m.station_id, m.parameter, iso(m.ts), m.value, m.unit, m.state, now),
                )
                n += cur.rowcount
            self._bump(c)
        return n

    def stations_with_latest(self, source_id: str, parameter: str, hours: int = 48) -> list[dict[str, Any]]:
        cutoff = iso(utcnow() - timedelta(hours=hours))
        out: list[dict[str, Any]] = []
        for s in self._query("SELECT * FROM stations WHERE source_id=? ORDER BY water, km DESC", (source_id,)):
            series = self._query(
                """SELECT ts, value, unit, state FROM measurements
                   WHERE source_id=? AND station_id=? AND parameter=? AND ts>=? ORDER BY ts""",
                (source_id, s["station_id"], parameter, cutoff),
            )
            d = dict(s)
            d["meta"] = json.loads(d["meta"])
            d["series"] = [dict(r) for r in series]
            d["latest"] = d["series"][-1] if d["series"] else None
            out.append(d)
        return out

    # -------------------------------------------------------------------- Cache
    def cache_put(self, key: str, source_id: str, payload: Any) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO kv_cache (key, source_id, fetched_at, payload) VALUES (?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload""",
                (key, source_id, iso(utcnow()), json.dumps(payload, separators=(",", ":"))),
            )
            self._bump(c)

    def cache_get(self, key: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM kv_cache WHERE key=?", (key,))
        if not rows:
            return None
        r = rows[0]
        return {"source_id": r["source_id"], "fetched_at": r["fetched_at"], "payload": json.loads(r["payload"])}

    # ---------------------------------------------------- Collector-Läufe / Zustand
    def get_state(self, source_id: str) -> dict[str, Any]:
        rows = self._query("SELECT * FROM collector_state WHERE source_id=?", (source_id,))
        if rows:
            return dict(rows[0])
        return {"source_id": source_id, "last_success": None, "last_attempt": None, "last_error": None,
                "failing_since": None, "consecutive_failures": 0, "open_until": None}

    def record_run(
        self, source_id: str, started: datetime, duration_ms: int, ok: bool,
        n_new: int = 0, n_seen: int = 0, error: str | None = None,
        breaker_threshold: int = 5, breaker_cooldown_s: int = 900,
    ) -> None:
        now = utcnow()
        with self._tx() as c:
            c.execute(
                """INSERT INTO collector_runs (source_id, started_at, duration_ms, ok, n_new, n_seen, error)
                   VALUES (?,?,?,?,?,?,?)""",
                (source_id, iso(started), duration_ms, int(ok), n_new, n_seen, error),
            )
            st = self.get_state(source_id)
            if ok:
                st.update(last_success=iso(now), last_attempt=iso(now), last_error=(error or None),
                          failing_since=None, consecutive_failures=0, open_until=None)
            else:
                fails = st["consecutive_failures"] + 1
                st.update(last_attempt=iso(now), last_error=(error or "")[:500],
                          consecutive_failures=fails,
                          failing_since=st["failing_since"] or iso(now))
                if fails >= breaker_threshold:
                    st["open_until"] = iso(now + timedelta(seconds=breaker_cooldown_s))
            c.execute(
                """INSERT INTO collector_state (source_id, last_success, last_attempt, last_error,
                       failing_since, consecutive_failures, open_until)
                   VALUES (:source_id,:last_success,:last_attempt,:last_error,:failing_since,
                           :consecutive_failures,:open_until)
                   ON CONFLICT(source_id) DO UPDATE SET
                       last_success=:last_success, last_attempt=:last_attempt, last_error=:last_error,
                       failing_since=:failing_since, consecutive_failures=:consecutive_failures,
                       open_until=:open_until""",
                st,
            )
            self._bump(c)

    def recent_runs(self, source_id: str, n: int = 10) -> list[dict[str, Any]]:
        return [dict(r) for r in self._query(
            "SELECT * FROM collector_runs WHERE source_id=? ORDER BY id DESC LIMIT ?", (source_id, n))]

    # ---------------------------------------------------------------- Wartung
    def purge(self, retention_days: int) -> None:
        cutoff = iso(utcnow() - timedelta(days=retention_days))
        with self._tx() as c:
            c.execute("DELETE FROM events WHERE active=0 AND last_seen < ?", (cutoff,))
            c.execute("DELETE FROM measurements WHERE ts < ?", (cutoff,))
            c.execute("DELETE FROM collector_runs WHERE started_at < ?", (cutoff,))

    def _bump(self, c: sqlite3.Connection) -> None:
        c.execute(
            "INSERT INTO meta (key, value) VALUES ('data_version','1') "
            "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1"
        )

    def data_version(self) -> int:
        rows = self._query("SELECT value FROM meta WHERE key='data_version'")
        return int(rows[0]["value"]) if rows else 0

    def ping(self) -> bool:
        return self._query("SELECT 1 x")[0]["x"] == 1


__all__ = ["Storage", "SCHEMA"]
