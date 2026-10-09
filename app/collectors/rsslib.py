"""Gemeinsame RSS-Hilfen für Meldungs-Collector.

Zweck:    RSS 2.0 sicher lesen. Externe XML-Dateien sind unvertrauenswürdig: Dokumente mit DOCTYPE oder ENTITY
          werden abgelehnt (Schutz vor Entity-Expansion), Texte laufen durch clean_text.
          Es werden nur Titel, Link, Zeit und Kategorien gelesen. Beschreibung und Volltext gehören nicht zum Zuschnitt.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..sanitize import clean_text
from .base import SourceError


@dataclass
class Item:
    title: str
    link: str
    published: datetime
    categories: list[str] = field(default_factory=list)
    description: str = ""   # nur für den Ortsvorspann (Datumszeile) gedacht, wird nie gespeichert


def parse_rss(data: bytes, keep_description: bool = False) -> list[Item]:
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data[:65536].lower():
        raise SourceError("RSS: DOCTYPE/ENTITY im Dokument, abgelehnt")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SourceError(f"RSS: kein gültiges XML ({exc})") from exc
    channel = root.find("channel")
    if channel is None:
        raise SourceError("RSS: Element 'channel' fehlt")
    out: list[Item] = []
    for it in channel.findall("item"):
        title = clean_text(it.findtext("title"), 300)
        link = (it.findtext("link") or "").strip()
        try:
            pub = parsedate_to_datetime((it.findtext("pubDate") or "").strip())
        except (TypeError, ValueError):
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if not title or not re.match(r"^https://", link):
            continue
        out.append(Item(
            title=title, link=link, published=pub.astimezone(timezone.utc),
            categories=[clean_text(c.text, 80) for c in it.findall("category") if c.text],
            description=clean_text(it.findtext("description"), 200) if keep_description else "",
        ))
    return out
