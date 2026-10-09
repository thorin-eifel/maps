"""Luftverkehr-Collector über adsb.lol (Community-ADS-B, ODbL 1.0).

Quelle:     https://api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm}
Lizenz:     siehe sources.yaml (ODbL 1.0 laut Betreiber; Nutzungsbedingungen noch zu bestätigen)
Intervall:  15 s (Live-Schleife, siehe app/live.py; ein Abruf je Durchlauf, nie mehr als einer je 10 s)
Beispiel:   python -m app.collect --once --only adsblol

Warum nicht OpenSky: Die OpenSky-Bedingungen verlangen für kommerzielle Stellen, auch bei
interner Nutzung, eine Lizenz. Das Lagebild war ursprünglich ein Firmen-Schaufenster (CTW GmbH), seit Oktober 2026 ist es ein privates Projekt; die Prüfung wird bei Gelegenheit neu bewertet. Ohne Lizenz kein Collector.

Datenschutz (Projektanweisung 2 und 7): Ereignisse statt Personen. Flugzeugkennungen lassen sich
Haltern zuordnen. Deshalb werden Hex-Code, Rufzeichen, Kennzeichen und Flugzeugtyp nie gespeichert.
Die Ereignis-ID ist ein Hash aus Hex-Code und einem täglich wechselnden Salz (in kv_cache, nicht im
Export). Innerhalb eines Tages bleibt sie stabil, damit der Upsert die Position überschreibt statt
Spuren anzuhäufen; über Tage hinweg lässt sie sich nicht verknüpfen. Es gibt keine Bewegungshistorie.

Geometrie: Punkt. Flugzeuge am Boden werden verworfen (kein Luftverkehr). Der Radiusfilter passiert
am Rand, die Abfrage holt bewusst etwas mehr als 120 km (Rand des Kreises).
Gültigkeit: valid_to = Abrufzeit + max(90 s, 4 × Intervall); fällt der Collector aus, verschwinden die Punkte von selbst.
Zusatzangaben (attrs): Kurs (Grad) und Geschwindigkeit (km/h), damit die Karte das Symbol drehen und zwischen zwei
Abrufen weiterrücken kann. Beides steht auch im Klartext der Zusammenfassung; es ist keine Kennung.
Dazu `klass`, eine grobe Klasse für die Darstellung: civil, mil (Militär-Kennzeichen der adsb.lol-Datenbank, Bit 0 von
`dbFlags`), heli (Kategorie A7) oder milheli. Gespeichert wird nur diese Klasse, nie das Kennzeichen, aus dem sie stammt.
Transpondercodes 7500/7600/7700 erscheinen als Hinweis (notice, Konfidenz 0,4), nicht als Warnung:
sie sind ein Signal des Flugzeugs, häufig Test oder Fehlbedienung, und nicht bestätigt.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import timedelta
from typing import Any

from .. import config
from ..models import Event, Severity, iso, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

KM_PER_NM = 1.852
FETCH_RADIUS_NM = 70  # ≈ 130 km; Feinfilter danach auf 120 km
MIN_VALID_S = 90
SALT_KEY = "adsblol:salt"

CATEGORY_LABEL = {
    "A1": "Leichtflugzeug", "A2": "Kleinflugzeug", "A3": "Verkehrsflugzeug", "A4": "Verkehrsflugzeug",
    "A5": "Großflugzeug", "A6": "Hochleistungsflugzeug", "A7": "Hubschrauber",
    "B1": "Segelflugzeug", "B2": "Ballon oder Luftschiff", "B4": "Ultraleichtflugzeug", "B6": "Drohne",
}
EMERGENCY_SQUAWK = {
    "7500": "Transpondercode 7500 (Sonderfall Luftsicherheit)",
    "7600": "Transpondercode 7600 (Funkausfall)",
    "7700": "Transpondercode 7700 (Allgemeiner Notfall)",
}


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _klass(ac: dict[str, Any]) -> str:
    """Grobe Klasse für die Karte: civil, mil, heli, milheli. Das Datenbank-Kennzeichen selbst wird nicht weitergegeben."""
    flags = ac.get("dbFlags")
    mil = isinstance(flags, int) and not isinstance(flags, bool) and bool(flags & 1)
    heli = str(ac.get("category") or "") == "A7"
    return "milheli" if mil and heli else "mil" if mil else "heli" if heli else "civil"


def _pseudo_id(hex_code: str, salt: str) -> str:
    return "adsblol:" + hashlib.sha256(f"{salt}:{hex_code}".encode()).hexdigest()[:12]


class AdsbLolCollector(Collector):
    async def _daily_salt(self, today: str) -> tuple[str, dict[str, Any] | None]:
        """Salz des Tages aus dem Cache, sonst neu. Zweiter Wert: Cache-Eintrag, falls zu schreiben."""
        cached = await asyncio.to_thread(self.storage.cache_get, SALT_KEY)
        payload = cached["payload"] if cached else None
        if isinstance(payload, dict) and payload.get("day") == today and payload.get("salt"):
            return str(payload["salt"]), None
        fresh = {"day": today, "salt": secrets.token_hex(16)}
        return fresh["salt"], fresh

    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        url = f"{base}/v2/point/{config.CENTER_LAT}/{config.CENTER_LON}/{FETCH_RADIUS_NM}"
        data = await self.fetch_json(url)
        aircraft = data.get("ac") if isinstance(data, dict) else None
        if not isinstance(aircraft, list):
            raise SourceError("Schlüssel 'ac' fehlt")
        now = utcnow()
        salt, new_salt = await self._daily_salt(iso(now)[:10])
        events: dict[str, Event] = {}
        for ac in aircraft:
            ev = self._normalize(ac, salt, now)
            if ev is not None:
                events[ev.id] = ev
        cache = {SALT_KEY: new_salt} if new_salt else {}
        return CollectResult(events=list(events.values()), cache=cache, complete=True)

    def _normalize(self, ac: Any, salt: str, now) -> Event | None:
        if not isinstance(ac, dict):
            return None
        hex_code = str(ac.get("hex") or "").strip().lower()
        lat, lon = _num(ac.get("lat")), _num(ac.get("lon"))
        if not hex_code or lat is None or lon is None:
            return None
        if ac.get("alt_baro") == "ground":
            return None
        geometry = {"type": "Point", "coordinates": [lon, lat]}
        if not self.keep(geometry):
            return None
        alt_ft = _num(ac.get("alt_baro"))
        gs_kn = _num(ac.get("gs"))
        track = _num(ac.get("track"))
        squawk = str(ac.get("squawk") or "")
        klass = _klass(ac)
        label = CATEGORY_LABEL.get(str(ac.get("category") or ""), "Luftfahrzeug")
        if klass in ("mil", "milheli"):
            label = "Militärhubschrauber" if klass == "milheli" else "Militärflugzeug"

        parts = []
        if alt_ft is not None:
            parts.append(f"Höhe FL{round(alt_ft / 100):03d} (ca. {round(alt_ft * 0.3048, -1):.0f} m)")
        if gs_kn is not None:
            parts.append(f"{round(gs_kn * KM_PER_NM):d} km/h")
        if track is not None:
            parts.append(f"Kurs {round(track) % 360:d}°")
        summary = ", ".join(parts) or "Position ohne weitere Angaben"

        severity: Severity = "info"
        confidence = 1.0
        title = label
        if squawk in EMERGENCY_SQUAWK:
            severity, confidence = "notice", 0.4
            title = f"{label}: {EMERGENCY_SQUAWK[squawk]}"
            summary += ". Signal des Transponders, nicht bestätigt; häufig Test oder Fehlbedienung."
        return Event(
            id=_pseudo_id(hex_code, salt),
            source_id=self.entry.id,
            type="aircraft",
            title=clean_text(title, 120),
            summary=clean_text(summary, 300),
            severity=severity,
            confidence=confidence,
            geometry=geometry,
            region_tag="DE",
            valid_to=now + timedelta(seconds=max(MIN_VALID_S, 4 * self.entry.intervall)),
            attrs={k: v for k, v in (("klass", klass), ("track", round(track) % 360 if track is not None else None), ("speed_kmh", round(gs_kn * KM_PER_NM) if gs_kn is not None else None)) if v is not None},
            fetched_at=now,
            raw_ref="https://adsb.lol/",
        )


COLLECTOR = AdsbLolCollector
