"""DWD-Warnungen (WFS, Layer dwd:Warnungen_Landkreise).

Quelle:     https://maps.dwd.de/geoserver/dwd/ows  (WFS 2.0.0, GeoJSON)
Lizenz:     GeoNutzV, siehe sources.yaml
Intervall:  300 s
Beispiel:   python -m app.collect --once --only dwd_warnungen

Achtung Achsenreihenfolge: Dieser Server erwartet die BBox als lon,lat (live geprüft an
dwd:Warngebiete_Gemeinden). Die Reihenfolge lat,lon liefert leere Antworten — auch bei Warnlage.

Feldnamen (ID, EVENT, SEVERITY, HEADLINE, DESCRIPTION, ONSET, EXPIRES, STATUS, MSGTYPE) folgen der
DWD-Dokumentation; zum Bauzeitpunkt lag keine Warnung vor. Fehlt ein Pflichtfeld, wird die
Meldung mit Log-Warnung verworfen, statt zu raten. Mehrere Kreis-Polygone derselben Warnung
werden zu einem Ereignis zusammengefasst.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import config
from ..models import Event, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError
from .severity import cap_to_severity


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class DwdWarnungenCollector(Collector):
    async def collect(self) -> CollectResult:
        lat_min, lon_min, lat_max, lon_max = config.BBOX
        data = await self.fetch_json(
            self.entry.url,
            params={
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeName": self.entry.params["layer"],
                "outputFormat": "application/json",
                "srsName": "EPSG:4326",
                "bbox": f"{lon_min},{lat_min},{lon_max},{lat_max},EPSG:4326",  # lon,lat!
            },
        )
        if not isinstance(data, dict) or "features" not in data:
            raise SourceError("WFS-Antwort ohne 'features'")

        groups: dict[str, list[dict[str, Any]]] = {}
        for feat in data["features"]:
            props = {str(k).upper(): v for k, v in (feat.get("properties") or {}).items()}
            wid = props.get("ID") or props.get("IDENTIFIER")
            if not wid or not props.get("EVENT") or not feat.get("geometry"):
                self.log.warning("Feature ohne ID/EVENT/Geometrie verworfen: %s", list(props)[:8])
                continue
            groups.setdefault(str(wid), []).append({"props": props, "geometry": feat["geometry"]})

        now = utcnow()
        events: list[Event] = []
        for wid, members in groups.items():
            props = members[0]["props"]
            if str(props.get("STATUS", "Actual")).lower() not in ("actual",):
                continue
            if str(props.get("MSGTYPE", "Alert")).lower() == "cancel":
                continue
            geoms = [m["geometry"] for m in members]
            geometry = geoms[0] if len(geoms) == 1 else {"type": "GeometryCollection", "geometries": geoms}
            if not self.keep(geometry):
                continue
            title = clean_text(props.get("HEADLINE") or props.get("EVENT"), 300)
            events.append(
                Event(
                    id=f"dwd:{wid}",
                    source_id=self.entry.id,
                    type="weather",
                    title=title,
                    summary=clean_text(props.get("DESCRIPTION"), 700),
                    severity=cap_to_severity(props.get("SEVERITY")),
                    geometry=geometry,
                    region_tag="DE",
                    valid_from=_dt(props.get("ONSET")) or _dt(props.get("EFFECTIVE")),
                    valid_to=_dt(props.get("EXPIRES")),
                    fetched_at=now,
                    raw_ref="https://www.dwd.de/DE/wetter/warnungen/warnWetter_node.html",
                )
            )
        return CollectResult(events=events)


COLLECTOR = DwdWarnungenCollector
