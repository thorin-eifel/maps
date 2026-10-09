"""Themenradar aus öffentlichen Mastodon-Hashtag-Zeitleisten (nur Zählungen, keine Beiträge, keine Konten).

Quelle:     https://<instanz>/api/v1/timelines/tag/<hashtag> (öffentliche, unauthentifizierte Mastodon-API; Standard mastodon.social)
Betreiber:  Mastodon gGmbH (mastodon.social); Beiträge gehören ihren Verfassern
Lizenz:     keine; wir speichern keine Beiträge. robots.txt lässt /api/v1/timelines zu, die Nutzungsbedingungen verbieten
            automatisierten Abruf der öffentlichen API nicht (gelesen 2026-09-30, lizenz_geprueft bleibt false wegen Einzelinstanz)
Intervall:  3600 s; je Hashtag ein Abruf (Standard 10 Hashtags, Pause 1 s)
Beispiel:   python -m app.collect --once --only mastodon_themen

Was gespeichert wird: Anzahl der Beiträge der letzten 24 Stunden je Regions-Hashtag und eine Rangliste begleitender Hashtags.
Ein begleitendes Hashtag erscheint nur, wenn mindestens drei verschiedene Konten es in dieser Auswertung genutzt haben; die Konten-Kennungen
liegen nur im Arbeitsspeicher dieses Laufs und werden nie geschrieben. Nicht gelesen und nicht gespeichert werden: Text, Anzeigename,
Kontoname, Bilder, Links, Antworten. Beiträge mit Inhaltswarnung oder als sensibel markiert fallen ganz weg. Das Ergebnis ist ein Themenzähler,
keine Stimmungsanalyse und keine Abbildung der Region: Mastodon ist klein und deutschlandweit gestreut.
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import utcnow
from .base import Collector, CollectResult, SourceError

WINDOW_H = 24
K_MIN = 3
TAG_OK = re.compile(r"^[\wäöüß]{2,30}$", re.I)
DEFAULT_TAGS = ["trier", "eifel", "bitburg", "irrel", "echternach", "luxemburg", "luxembourg", "wittlich", "saarburg", "mosel"]


def aggregate(timelines: dict[str, list[Any]], now: datetime) -> dict[str, Any]:
    """Reine Funktion: {region_tag: [Status-JSON]} → Zählungen. Verwendet nur created_at, tags[].name, account.id, sensitive, spoiler_text."""
    cutoff = now - timedelta(hours=WINDOW_H)
    region_counts: dict[str, int] = {}
    co_posts: Counter[str] = Counter()
    co_accounts: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    for region, posts in timelines.items():
        n = 0
        for p in posts:
            if not isinstance(p, dict) or p.get("sensitive") or p.get("spoiler_text"):
                continue
            try:
                created = datetime.fromisoformat(str(p["created_at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                continue
            n += 1
            pid = str(p.get("uri") or p.get("id"))
            if pid in seen:
                continue
            seen.add(pid)
            acct = str((p.get("account") or {}).get("id", ""))
            for t in p.get("tags") or []:
                name = str((t or {}).get("name", "")).lower()
                if not TAG_OK.match(name) or name in timelines:
                    continue
                co_posts[name] += 1
                co_accounts[name].add(acct)
        region_counts[region] = n
    topics = [{"tag": t, "posts": c} for t, c in co_posts.most_common() if len(co_accounts[t]) >= K_MIN][:15]
    return {"window_h": WINDOW_H, "k_min": K_MIN, "regions": [{"tag": k, "posts": v} for k, v in sorted(region_counts.items(), key=lambda kv: -kv[1])],
            "topics": topics, "posts_total": len(seen), "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


class MastodonThemenCollector(Collector):
    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        tags = [t for t in (self.entry.params.get("hashtags") or DEFAULT_TAGS) if TAG_OK.match(str(t))]
        if not tags:
            raise SourceError("Mastodon: params.hashtags leer")
        timelines: dict[str, list[Any]] = {}
        failed = 0
        for t in tags:
            try:
                data = await self.fetch_json(f"{base}/api/v1/timelines/tag/{t}", params={"limit": 40})
            except SourceError as exc:
                self.log.warning("Hashtag %s: %s", t, exc)
                failed += 1
                continue
            if not isinstance(data, list):
                raise SourceError("Mastodon: Liste erwartet")
            timelines[t] = data
            await asyncio.sleep(1.0)
        if not timelines:
            raise SourceError("Mastodon: kein Hashtag abrufbar")
        agg = aggregate(timelines, utcnow())
        agg["instance"] = base.split("//", 1)[-1]
        return CollectResult(cache={"themenradar": agg}, writes_events=False, complete=failed == 0,
                             note=f"{agg['posts_total']} Beiträge gezählt, {len(agg['topics'])} Themen ab {K_MIN} Konten" + (f", {failed} Hashtags ohne Antwort" if failed else ""))


COLLECTOR = MastodonThemenCollector
