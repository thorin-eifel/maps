"""Wetterwarnungen Belgien, Frankreich, Luxemburg (MeteoAlarm, Feeds der nationalen Wetterdienste).

Quelle:     https://feeds.meteoalarm.org/api/v1/warnings/feeds-<land>  (JSON, CAP-Inhalt); Länder: belgium, france, luxembourg
Betreiber:  EUMETNET / MeteoAlarm; Herausgeber der Warnungen: KMI/IRM (BE), Météo-France (FR), MeteoLux (LU)
Lizenz:     laut Anbieter "Bedingungen gleichwertig CC BY 4.0, mit zusätzlichen Auflagen für Weiterverbreitung"; der Wortlaut der
            Auflagen ließ sich nicht lesen (lizenz_geprueft false). Deshalb zeigen wir nur Stufe, Art, Gebiet, Zeitraum und Link,
            keinen Beschreibungstext, und nennen Herausgeber und MeteoAlarm.
Intervall:  600 s
Beispiel:   python -m app.collect --once --only meteoalarm

Der Feed kennt Gebiete nur als NUTS-Code (BE34, FR413 ...). Die Grenzen liegen in app/data/nuts_meteoalarm.json (tools/build_nuts.py);
Gebiete, die den Radius nicht berühren, fehlen dort und fallen am Rand weg. Stufe 1 (grün, "AllClear") ist keine Warnung und
wird nicht gespeichert. Jede Warnung kommt in mehreren Sprachen vor; wir nehmen Deutsch, sonst Französisch, sonst Englisch.
Spätere Meldungen ersetzen frühere über das Feld "references" (Update, Cancel). Die Quelle kennt keine Personen.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import Event, Severity, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

FEEDS = {"BE": "belgium", "FR": "france", "LU": "luxembourg"}
URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-{land}"
LEVEL = {2: ("notice", "gelb"), 3: ("warning", "orange"), 4: ("critical", "rot")}
TYPE_LABEL = {1: "Wind", 2: "Schnee/Eis", 3: "Gewitter", 4: "Nebel", 5: "Hitze", 6: "Kälte", 7: "Küste", 8: "Waldbrand", 9: "Lawinen",
              10: "Starkregen", 11: "Hochwasser", 12: "Regen/Flut", 13: "Gewitter/Regen"}
LANG_PREF = ("de", "fr", "en")
ALIAS = {"LU000": "LU00"}
_AREAS_FILE = Path(__file__).resolve().parent.parent / "data" / "nuts_meteoalarm.json"


def load_areas(path: Path = _AREAS_FILE) -> dict[str, dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dt(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        d = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _param(info: dict[str, Any], name: str) -> str | None:
    for p in info.get("parameter") or []:
        if p.get("valueName") == name:
            return str(p.get("value"))
    return None


def _num(value: str | None) -> int | None:
    try:
        return int((value or "").split(";")[0].strip())
    except ValueError:
        return None


def _pick_lang(infos: list[dict[str, Any]]) -> dict[str, Any] | None:
    for pref in LANG_PREF:
        for i in infos:
            if str(i.get("language", "")).lower().startswith(pref):
                return i
    return infos[0] if infos else None


def _https(url: Any) -> str | None:
    u = str(url or "")
    return u if u.startswith("https://") and len(u) < 400 else None


def parse_feed(data: Any, land: str, now: datetime, areas: dict[str, dict[str, Any]]) -> tuple[list[Event], dict[str, int]]:
    """Reine Funktion (testbar mit Fixtures). land: BE, FR oder LU (für region_tag)."""
    warnings = data.get("warnings") if isinstance(data, dict) else None
    if not isinstance(warnings, list):
        raise SourceError("MeteoAlarm: Feed ohne 'warnings'")
    stats = {"alerts": len(warnings), "superseded": 0, "not_actual": 0, "green": 0, "expired": 0, "outside": 0}
    replaced: set[str] = set()
    for w in warnings:
        refs = str((w.get("alert") or {}).get("references") or "").split()
        for ref in refs:
            parts = ref.split(",")
            if len(parts) >= 2:
                replaced.add(parts[1])
    events: dict[str, Event] = {}
    for w in warnings:
        a = w.get("alert") or {}
        if a.get("identifier") in replaced:
            stats["superseded"] += 1
            continue
        if a.get("status") != "Actual" or a.get("msgType") == "Cancel":
            stats["not_actual"] += 1
            continue
        # Gebiet, Stufe und Art stecken in jeder Sprachfassung gleich; die Fassung bestimmt nur den Text.
        infos = [i for i in a.get("info") or [] if isinstance(i, dict)]
        by_area: dict[str, list[dict[str, Any]]] = {}
        for i in infos:
            for ar in i.get("area") or []:
                for g in ar.get("geocode") or []:
                    code = ALIAS.get(str(g.get("value")), str(g.get("value")))
                    by_area.setdefault(code, []).append(i)
        for code, cand in by_area.items():
            if code not in areas:
                stats["outside"] += 1
                continue
            info = _pick_lang(cand)
            if info is None:
                continue
            level = _num(_param(info, "awareness_level"))
            if level not in LEVEL:
                stats["green"] += 1
                continue
            start = _dt(info.get("onset") or info.get("effective"))
            end = _dt(info.get("expires"))
            if end is not None and end <= now:
                stats["expired"] += 1
                continue
            sev: Severity = LEVEL[level][0]  # type: ignore[assignment]
            kind = _num(_param(info, "awareness_type"))
            label = TYPE_LABEL.get(kind or 0, "Wetter")
            area_name = areas[code]["name"]
            uid = hashlib.sha1(f"{code}|{kind}|{level}|{start}|{end}".encode()).hexdigest()[:16]
            head = clean_text(info.get("event") or info.get("headline") or label, 160)
            ev = Event(
                id=f"meteoalarm:{uid}", source_id="meteoalarm", type="weather",
                title=f"{head} ({area_name})", summary=clean_text(f"{LEVEL[level][1].capitalize()}e Stufe {level}, {label}, Herausgeber: {info.get('senderName') or a.get('sender') or 'Wetterdienst'}", 300),
                severity=sev, confidence=1.0, geometry=areas[code]["geometry"], region_tag=land,
                valid_from=start, valid_to=end, fetched_at=now, raw_ref=_https(info.get("web")),
                attrs={"stufe": level, "art": label, "gebiet": area_name, "herausgeber": clean_text(info.get("senderName") or "", 120)},
            )
            events[ev.id] = ev
    return list(events.values()), stats


class MeteoAlarmCollector(Collector):
    async def collect(self) -> CollectResult:
        areas = load_areas()
        now = utcnow()
        events: list[Event] = []
        notes: list[str] = []
        failed = 0
        for land, slug in FEEDS.items():
            try:
                data = await self.fetch_json(URL.format(land=slug), allow_empty=True)
            except SourceError as exc:
                failed += 1
                notes.append(f"{land} nicht erreichbar")
                self.log.warning("MeteoAlarm %s: %s", land, exc)
                continue
            if not data:  # Luxemburg liefert bei Ruhe einen leeren Körper
                notes.append(f"{land} keine Warnungen")
                continue
            ev, st = parse_feed(data, land, now, areas)
            events += ev
            notes.append(f"{land} {len(ev)} von {st['alerts']}")
        if failed == len(FEEDS):
            raise SourceError("MeteoAlarm: alle Länderfeeds nicht erreichbar")
        return CollectResult(events=events, note="; ".join(notes), complete=failed == 0)


COLLECTOR = MeteoAlarmCollector
