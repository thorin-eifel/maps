"""Aufbereitung der Daten für die Oberfläche (reine Funktionen über Storage und Register).

Zweck:    Erzeugt die JSON-Strukturen, die app.export als statische Dateien schreibt
          (meta, events, gewaesser, wetter, status, sources).
Hinweis:  Zeitfenster („jetzt“, 24 h, 7 Tage) und die Quellen-Zustände „veraltet/nicht erreichbar“
          rechnet das Frontend gegen die Uhr des Betrachters neu; hier steht der Stand zum Exportzeitpunkt.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from . import __version__, config, geo
from .region import REGION
from .db import Storage
from .models import SEVERITY_ORDER, iso, utcnow
from .registry import Registry, SourceEntry

ALLOWED_TYPES = {"traffic", "congestion", "weather", "flood", "warning", "air", "radiation", "earthquake", "fire", "transit", "news", "social_signal", "aircraft"}
WINDOWS = {"now": 0, "24h": 24, "7d": 168}

DISCLAIMER = (
    "Kein amtliches Warnsystem, keine Gewähr. Im Notfall 112 wählen und offizielle Warn-Apps "
    "(NINA, KATWARN) nutzen. Dieses Dashboard ersetzt weder NINA noch die Leitstelle."
)


def parse_ts(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def source_status(entry: SourceEntry, state: dict[str, Any], n_active: int, now: datetime | None = None) -> dict[str, Any]:
    """Zustand einer Quelle.

    down      – nie erfolgreich oder ≥ 3 Fehlläufe in Folge („nicht erreichbar seit …“)
    stale     – letzter Erfolg älter als das Dreifache des Intervalls
    degraded  – zuletzt ein Fehler, aber noch frische Daten
    ok        – sonst
    Dieselbe Regel steht in web/js/rules.js (Frontend rechnet gegen die Uhr des Betrachters).
    """
    now = now or utcnow()
    last_ok = parse_ts(state.get("last_success"))
    age = int((now - last_ok).total_seconds()) if last_ok else None
    fails = state.get("consecutive_failures", 0)
    if not entry.aktiv:
        status = "disabled"
    elif last_ok is None and state.get("last_attempt"):
        status = "down"
    elif last_ok is None:
        status = "pending"
    elif fails >= 3:
        status = "down"
    elif age is not None and age > 3 * entry.intervall:
        status = "stale"
    elif fails > 0:
        status = "degraded"
    else:
        status = "ok"
    return {
        "id": entry.id, "name": entry.name, "short_name": entry.kurzname or entry.name,
        "betreiber": entry.betreiber, "status": status,
        "last_success": state.get("last_success"), "last_attempt": state.get("last_attempt"),
        "age_s": age, "interval_s": entry.intervall, "failing_since": state.get("failing_since"),
        "consecutive_failures": fails, "last_error_or_note": state.get("last_error"),
        "circuit_open_until": state.get("open_until"), "active_events": n_active,
        "attribution": entry.namensnennung, "license": entry.lizenz, "license_verified": entry.lizenz_geprueft,
    }


def statuses(storage: Storage, registry: Registry) -> dict[str, dict[str, Any]]:
    return {e.id: source_status(e, storage.get_state(e.id), storage.count_active(e.id)) for e in registry.entries if e.art == "collector"}


def meta_payload(storage: Storage) -> dict[str, Any]:
    return {
        "name": "Was ist los bei uns?", "version": __version__,
        "center": {"lat": config.CENTER_LAT, "lon": config.CENTER_LON, "name": REGION.ref_name},
        "radius_km": REGION.radius_km if REGION.radius_km is not None else REGION.query_radius_km,  # Polygon: umschließender Kreis
        "region": REGION.meta(),
        "bbox": {"lat_min": config.BBOX[0], "lon_min": config.BBOX[1], "lat_max": config.BBOX[2], "lon_max": config.BBOX[3]},
        "disclaimer": DISCLAIMER, "data_version": storage.data_version(), "generated_at": iso(utcnow()),
    }


def events_payload(
    storage: Storage, registry: Registry, types: list[str] | None = None,
    within: str = "7d", min_severity: str | None = None, exclude_types: tuple[str, ...] = (), limit: int = 2000,
) -> dict[str, Any]:
    if within not in WINDOWS:
        raise ValueError(f"Unbekanntes Zeitfenster: {within}")
    if exclude_types and not types:
        types = sorted(ALLOWED_TYPES - set(exclude_types))
    if types:
        bad = [t for t in types if t not in ALLOWED_TYPES]
        if bad:
            raise ValueError(f"Unbekannter Typ: {', '.join(bad)}")
    rows = storage.active_events(types=types, min_severity=min_severity, within_hours=WINDOWS[within], limit=limit)
    st = statuses(storage, registry)
    now = utcnow()
    feats = []
    for r in rows:
        s = st.get(r["source_id"], {})
        fetched = parse_ts(r["fetched_at"])
        feats.append({
            "type": "Feature", "id": r["id"], "geometry": json.loads(r["geometry"]),
            "properties": {
                "id": r["id"], "source_id": r["source_id"], "source_name": s.get("name", r["source_id"]),
                "source_short": s.get("short_name", s.get("name", r["source_id"])),
                "attribution": s.get("attribution"), "type": r["type"], "title": r["title"],
                "summary": r["summary"], "severity": r["severity"], "severity_rank": SEVERITY_ORDER[r["severity"]],
                "confidence": r["confidence"], "lat": r["lat"], "lon": r["lon"], "distance_km": r["distance_km"],
                "region_tag": r["region_tag"], "valid_from": r["valid_from"], "valid_to": r["valid_to"],
                "first_seen": r["first_seen"], "fetched_at": r["fetched_at"],
                "age_s": int((now - fetched).total_seconds()) if fetched else None,
                "source_status": s.get("status"), "raw_ref": r["raw_ref"],
                "ai_generated": bool(r["ai_generated"]), "model": r["model"],
                "attrs": json.loads(r["attrs"]) if r["attrs"] else {},
            },
        })
    return {"type": "FeatureCollection", "generated_at": iso(now), "features": feats}


def aircraft_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Luftverkehr als eigene, kleine Datei: wird im Sekundentakt der Live-Schleife neu geschrieben."""
    return events_payload(storage, registry, types=["aircraft"], within="now")


def trend(series: list[dict[str, Any]], hours: int) -> float | None:
    """Änderung des letzten Werts gegenüber dem Wert vor `hours` Stunden."""
    if len(series) < 2:
        return None
    last_ts = parse_ts(series[-1]["ts"])
    if last_ts is None:
        return None
    target = last_ts - timedelta(hours=hours)
    older = [p for p in series if parse_ts(p["ts"]) <= target]
    return round(series[-1]["value"] - older[-1]["value"], 1) if older else None


GEW_SOURCES = (("pegelonline", "W"), ("hochwasser_rlp", "W"), ("lu_pegel", "W"), ("hubeau_pegel", "W"), ("wallonie_pegel", "W"))


def gewaesser_payload(storage: Storage, registry: Registry, series_step: int = 1) -> dict[str, Any]:
    """Pegel aus PEGELONLINE (WSV) und der Hochwasservorhersagezentrale RLP in einer Liste.

    series_step > 1 dünnt die Zeitreihe aus (jeder n-te Punkt plus der letzte) — hält die Datei klein.
    Jede Station trägt ihre Quelle (source_id, source_name, attribution), damit Popup und Tabelle richtig zitieren."""
    sts = statuses(storage, registry)
    stations: list[dict[str, Any]] = []
    for sid, param in GEW_SOURCES:
        st = sts.get(sid)
        if st is None:
            continue
        for s in storage.stations_with_latest(sid, param, hours=48):
            unit = (s.get("latest") or {}).get("unit")
            s["trend_cm_3h"] = trend(s["series"], hours=3) if unit in (None, "cm") else None  # auf voller Auflösung, vor dem Ausdünnen
            if series_step > 1 and len(s["series"]) > 2:
                thin = s["series"][::series_step]
                if thin[-1] is not s["series"][-1]:
                    thin.append(s["series"][-1])
                s["series"] = thin
            s["source_id"], s["source_name"], s["attribution"] = sid, st["short_name"], st["attribution"]
            s["source_status"] = st["status"]
            stations.append(s)
    stations.sort(key=lambda s: ((s.get("water") or "~"), -(s.get("km") or 0)))
    return {"source": sts.get("pegelonline"), "sources": [sts[i] for i, _ in GEW_SOURCES if i in sts],
            "stations": stations, "generated_at": iso(utcnow())}


UMWELT_SOURCES = (
    ("bfs_odl", "radiation", ("odl",)),
    ("uba_luft", "air", ("lqi", "NO2", "PM10", "PM2.5", "O3")),
    ("irceline", "air", ("NO2", "PM10", "PM2.5", "O3")),
    ("kmi_stationen", "weather", ("temperature", "relative_humidity", "pressure_msl", "wind_speed_10", "wind_gust_speed_10")),
    ("dwd_stationen", "weather", ("temperature", "relative_humidity", "pressure_msl", "wind_speed_10", "wind_gust_speed_10", "precipitation_60")),
)


def umwelt_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Messstationen für Strahlung (BfS), Luft (UBA) und Wetter (DWD): je Station der jüngste Wert je Messgröße, dazu die letzten 24 Stunden."""
    sts = statuses(storage, registry)
    cutoff = iso(utcnow() - timedelta(hours=24))
    out: list[dict[str, Any]] = []
    for sid, kind, params in UMWELT_SOURCES:
        st = sts.get(sid)
        if st is None:
            continue
        for s in storage._query("SELECT * FROM stations WHERE source_id=? ORDER BY name", (sid,)):  # noqa: SLF001
            values: dict[str, Any] = {}
            for prm in params:
                rows = storage._query(  # noqa: SLF001
                    "SELECT ts, value, unit, state FROM measurements WHERE source_id=? AND station_id=? AND parameter=? "
                    "AND ts>=? ORDER BY ts", (sid, s["station_id"], prm, cutoff))
                if rows:
                    d = [dict(r) for r in rows]
                    values[prm] = {**d[-1], "series": [round(r["value"], 3) for r in d][-24:]}
            if not values:
                continue
            out.append({
                "source_id": sid, "source_name": st["short_name"], "attribution": st["attribution"], "source_status": st["status"],
                "kind": kind, "station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"],
                "distance_km": s["distance_km"], "meta": json.loads(s["meta"]), "values": values,
            })
    return {"sources": [sts[i] for i, _, _ in UMWELT_SOURCES if i in sts], "stations": out, "generated_at": iso(utcnow())}


def radar_payload(storage: Storage, registry: Registry) -> tuple[dict[str, Any], bytes | None]:
    """Regenradar: Metadaten für radar.json und die PNG-Bytes für radar.png (None, wenn noch nie geholt)."""
    import base64

    st = statuses(storage, registry).get("dwd_radar")
    row = storage.cache_get("radar")
    meta: dict[str, Any] = {"source": st, "generated_at": iso(utcnow()), "time": None, "corners": None}
    if not row:
        return meta, None
    cached = row["payload"]
    meta["time"], meta["corners"] = cached["time"], cached["corners"]
    return meta, base64.b64decode(cached["png_b64"])


def blitz_payload(storage: Storage, registry: Registry) -> tuple[dict[str, Any], bytes | None]:
    """Blitze (EUMETSAT MTG-LI): Metadaten für blitz.json und die PNG-Bytes für blitz.png (None, wenn noch nie geholt)."""
    import base64

    st = statuses(storage, registry).get("eumetsat_li")
    row = storage.cache_get("blitz")
    meta: dict[str, Any] = {"source": st, "generated_at": iso(utcnow()), "time": None, "corners": None, "counts": None, "window_min": None}
    if not row:
        return meta, None
    c = row["payload"]
    meta.update(time=c["time"], corners=c["corners"], counts=c["counts"], window_min=c["window_min"])
    return meta, base64.b64decode(c["png_b64"])


def wind_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """10-m-Wind (ICON-D2) als Gitter für die Partikelansicht; `grid` ist None, solange nie etwas geholt wurde."""
    st = statuses(storage, registry).get("dwd_icon_d2_wind")
    row = storage.cache_get("wind")
    return {"source": st, "generated_at": iso(utcnow()), "grid": row["payload"] if row else None}


def haltestellen_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Bahnhöfe und Haltestellen der Schiene (Bahn, Tram) im Radius aus dem GTFS-Index; Busse bleiben draußen (zu viele Punkte).

    Gleisabschnitte derselben Station (gleicher Name, wenige Meter Abstand) werden zu einem Punkt."""
    st = statuses(storage, registry).get("gtfs_static")
    row = storage.cache_get("gtfs_index")
    out: dict[str, Any] = {"source": st, "generated_at": iso(utcnow()), "stops": []}
    if not row:
        return out
    seen: set[tuple[str, float, float]] = set()
    for feed in row["payload"].get("feeds", {}).values():
        for name, lat, lon, modes in feed.get("stops", {}).values():
            mode = "rail" if "rail" in modes else "tram" if "tram" in modes else None
            key = (name, round(lat, 3), round(lon, 3))
            if mode and name and key not in seen:
                seen.add(key)
                out["stops"].append({"name": name, "lat": lat, "lon": lon, "mode": mode, "region": feed.get("region", "")})
    out["stops"].sort(key=lambda s: (s["name"], s["lat"]))
    return out


def landmarks_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Natürliche Landmarken (Höhlen, Wasserfälle, Quellen, Aussichtspunkte, Felsen) aus dem letzten Overpass-Abruf.

    Enthält nur Art, Name, Höhe und Koordinate; Gipfel stehen in den Kacheln, nicht hier."""
    st = statuses(storage, registry).get("osm_natur")
    row = storage.cache_get("landmarks")
    out: dict[str, Any] = {"source": st, "generated_at": iso(utcnow()), "fetched_at": None, "items": []}
    if row:
        out["fetched_at"] = row.get("fetched_at")
        out["items"] = row["payload"].get("items", [])
    return out


def anbau_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Weinberge und Obstanlagen als GeoJSON (Eigenschaft kind = vineyard|orchard) aus dem letzten Overpass-Abruf."""
    st = statuses(storage, registry).get("osm_anbau")
    row = storage.cache_get("anbau")
    out: dict[str, Any] = {"type": "FeatureCollection", "features": [], "source": st, "generated_at": iso(utcnow()), "fetched_at": None}
    if row:
        out["fetched_at"] = row.get("fetched_at")
        out["features"] = [{"type": "Feature", "id": i["id"], "properties": {"kind": i["kind"]}, "geometry": {"type": "Polygon", "coordinates": [i["ring"]]}}
                           for i in row["payload"].get("items", [])]
    return out


SACRAL_KINDS = ("church", "chapel", "cross", "shrine", "watermill", "windmill", "ford", "border", "gallows", "well")     # nur für die Karte um 1450: eigene Datei, wird nur dort geladen


def _infra_items(storage: Storage, registry: Registry, sacral: bool) -> dict[str, Any]:
    st = statuses(storage, registry).get("osm_infra")
    row = storage.cache_get("infrastruktur")
    out: dict[str, Any] = {"source": st, "generated_at": iso(utcnow()), "fetched_at": None, "items": []}
    if row:
        out["fetched_at"] = row.get("fetched_at")
        out["items"] = [i for i in row["payload"].get("items", []) if (i["kind"] in SACRAL_KINDS) == sacral]
    return out


def infrastruktur_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Windräder, Ladesäulen, Notfallpunkte, Wasserbauwerke, Brücken, Rastplätze aus dem letzten Overpass-Abruf (nur Art, Standort, Sachwert)."""
    return _infra_items(storage, registry, sacral=False)


def sakral_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Kirchen, Kapellen, Wegkreuze, Bildstöcke (gleiche Quelle, eigene Datei für die Karte um 1450)."""
    return _infra_items(storage, registry, sacral=True)


def routen_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Überregionale Wander- und Radrouten aus dem letzten Overpass-Abruf (Name, Kennzeichen, vereinfachte Linie)."""
    st = statuses(storage, registry).get("osm_routen")
    row = storage.cache_get("routen")
    out: dict[str, Any] = {"source": st, "generated_at": iso(utcnow()), "fetched_at": None, "items": []}
    if row:
        out["fetched_at"] = row.get("fetched_at")
        out["items"] = row["payload"].get("items", [])
    return out


WETTER_OBS_SOURCES = ("meteolux", "sensor_community")


def wetter_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    st = statuses(storage, registry).get("brightsky")
    forecast = storage.cache_get("forecast")
    stations = storage.stations_with_latest("brightsky", "temperature", hours=6)
    current: dict[str, Any] = {}
    station_info = None
    if stations:
        station_info = {k: stations[0][k] for k in ("station_id", "name", "lat", "lon", "distance_km")}
        sid = stations[0]["station_id"]
        for param in ("temperature", "relative_humidity", "pressure_msl", "wind_speed_10", "wind_gust_speed_10",
                      "precipitation_60", "cloud_cover", "visibility"):
            rows = storage._query(  # noqa: SLF001
                "SELECT ts, value, unit, state FROM measurements WHERE source_id='brightsky' AND station_id=? "
                "AND parameter=? ORDER BY ts DESC LIMIT 1", (sid, param))
            if rows:
                current[param] = dict(rows[0])
    # Weitere Beobachtungen (MeteoLux Findel, Sensor.Community-Raster) und ein zweites Vorhersagemodell (MET Norway)
    sts = statuses(storage, registry)
    others: list[dict[str, Any]] = []
    for sid in WETTER_OBS_SOURCES:
        src = sts.get(sid)
        if src is None:
            continue
        for s in storage._query("SELECT * FROM stations WHERE source_id=?", (sid,)):  # noqa: SLF001
            cur: dict[str, Any] = {}
            for param in ("temperature", "relative_humidity", "pressure_msl", "wind_speed_10", "wind_gust_speed_10"):
                rows = storage._query(  # noqa: SLF001
                    "SELECT ts, value, unit FROM measurements WHERE source_id=? AND station_id=? AND parameter=? "
                    "AND ts>=? ORDER BY ts DESC LIMIT 1", (sid, s["station_id"], param, iso(utcnow() - timedelta(hours=3))))
                if rows:
                    cur[param] = dict(rows[0])
            if not cur:
                continue
            others.append({"source_id": sid, "source_name": src["short_name"], "attribution": src["attribution"],
                           "source_status": src["status"], "station_id": s["station_id"], "name": s["name"],
                           "lat": s["lat"], "lon": s["lon"], "distance_km": s["distance_km"],
                           "meta": json.loads(s["meta"]), "current": cur})
    others.sort(key=lambda o: (o["source_id"] != "meteolux", o["distance_km"]))
    alt = storage.cache_get("forecast_metno")
    forecast_alt = {"source": sts.get("metno"), "hours": alt["payload"]["hours"], "updated_at": alt["payload"].get("updated_at"),
                    "fetched_at": alt["fetched_at"]} if alt and alt.get("payload") else {"source": sts.get("metno"), "hours": []}
    return {"source": st, "station": station_info, "current": current, "forecast": forecast, "others": others[:12],
            "forecast_alt": forecast_alt, "generated_at": iso(utcnow())}


def _cache_block(storage: Storage, key: str) -> dict[str, Any] | None:
    c = storage.cache_get(key)
    return {"fetched_at": c["fetched_at"], **c["payload"]} if c and isinstance(c.get("payload"), dict) else None


def indizes_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Waldbrand-/Graslandfeuerindex, Pollenflug und UV (DWD): Zahlen aus dem Cache, je Block mit Quellenstatus."""
    sts = statuses(storage, registry)
    gh = _cache_block(storage, "gesundheit") or {}
    return {
        "fire": {**(_cache_block(storage, "fire_index") or {"stations": []}), "source": sts.get("dwd_waldbrand")},
        "pollen": {**(gh.get("pollen") or {"regions": []}), "fetched_at": gh.get("fetched_at"), "source": sts.get("dwd_gesundheit")},
        "uv": {**(gh.get("uv") or {}), "fetched_at": gh.get("fetched_at"), "source": sts.get("dwd_gesundheit")},
        "generated_at": iso(utcnow()),
    }


FUELS = (("e5", "Super E5"), ("e10", "Super E10"), ("diesel", "Diesel"))


def kraftstoff_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Spritpreise der deutschen Seite (Tankerkönig): je Sorte Spanne und Median, dazu die Stationsliste sortiert nach Diesel (Name = Marke, Ort, Koordinaten; Straße und Hausnummer werden nicht übernommen).

    Luxemburg fehlt, weil es dort keine offenen Preise je Tankstelle gibt; das sagt die Anzeige, nicht erst das Kleingedruckte."""
    st = statuses(storage, registry).get("tankerkoenig")
    cutoff = iso(utcnow() - timedelta(hours=3))
    rows: list[dict[str, Any]] = []
    for s in storage._query("SELECT * FROM stations WHERE source_id='tankerkoenig'"):  # noqa: SLF001
        prices: dict[str, Any] = {}
        for code, _ in FUELS:
            r = storage._query(  # noqa: SLF001
                "SELECT ts, value FROM measurements WHERE source_id='tankerkoenig' AND station_id=? AND parameter=? AND ts>=? "
                "ORDER BY ts DESC LIMIT 1", (s["station_id"], code, cutoff))
            if r:
                prices[code] = {"value": r[0]["value"], "ts": r[0]["ts"]}
        if prices:
            meta = json.loads(s["meta"])
            rows.append({"name": s["name"], "ort": meta.get("ort"), "lat": s["lat"], "lon": s["lon"],
                         "distance_km": s["distance_km"], "prices": prices})
    stats: dict[str, Any] = {}
    for code, label in FUELS:
        vals = sorted(r["prices"][code]["value"] for r in rows if code in r["prices"])
        if vals:
            stats[code] = {"label": label, "n": len(vals), "min": vals[0], "median": vals[len(vals) // 2], "max": vals[-1]}
    rows.sort(key=lambda r: r["prices"].get("diesel", {}).get("value", 99))
    return {"source": st, "stations": rows[:200], "stats": stats, "lu": luxembourg_fuel(storage, registry), "generated_at": iso(utcnow())}


def luxembourg_fuel(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Luxemburg: amtliche Höchstpreise (STATEC) und Standorte der Tankstellen (OpenStreetMap). Keine Stationspreise, das trägt schon der Name."""
    sts = statuses(storage, registry)
    mx = _cache_block(storage, "lu_fuel_max") or {}
    stations = []
    for it in (_cache_block(storage, "lu_stations") or {}).get("items", []):
        d = geo.distance_to_ref_km(it["lat"], it["lon"])
        stations.append({"name": it["name"], "lat": it["lat"], "lon": it["lon"], "distance_km": round(d, 1)})
    return {"max_prices": mx.get("fuels", {}), "max_source": sts.get("statec_sprit"), "stations": stations,
            "stations_source": sts.get("osm_tankstellen_lu"), "kind": "max_price"}


def themen_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Themenradar: nur Zählungen (Hashtags, Beiträge je Fenster), nie Text oder Konten."""
    return {"source": statuses(storage, registry).get("mastodon_themen"),
            "radar": _cache_block(storage, "themenradar"), "generated_at": iso(utcnow())}


def status_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    sources = list(statuses(storage, registry).values())
    for s in sources:
        s["recent_runs"] = storage.recent_runs(s["id"], 8)
    rank = {"ok": 0, "pending": 1, "disabled": 1, "degraded": 2, "stale": 3, "down": 4}
    worst = max((s["status"] for s in sources), key=lambda x: rank[x], default="ok")
    return {"overall": worst, "sources": sources, "generated_at": iso(utcnow())}


def sources_payload(registry: Registry) -> dict[str, Any]:
    return {"sources": [e.public() for e in registry.entries], "disclaimer": DISCLAIMER}


def suche_payload(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Suchindex, dynamischer Teil: benannte Einrichtungen, Landmarken, Haltestellen, Routen und Pegel (Namen, Art, Punkt, nächster Ort)."""
    from . import search

    builder = search.Builder(search.PlaceIndex(search.load_places()))
    infra = _infra_items(storage, registry, sacral=False).get("items", []) + _infra_items(storage, registry, sacral=True).get("items", [])
    search.dynamic_entries(
        builder,
        infra=infra,
        landmarks=landmarks_payload(storage, registry).get("items", []),
        stops=haltestellen_payload(storage, registry).get("stops", []),
        routes=routen_payload(storage, registry).get("items", []),
        stations=gewaesser_payload(storage, registry).get("stations", []),
    )
    return builder.payload(generated_at=iso(utcnow()))
