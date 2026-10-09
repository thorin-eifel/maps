"""Bereinigung externer Texte (Feeds sind unvertrauenswürdig).

Zweck:    HTML entfernen, Entities auflösen, Whitespace normalisieren, kürzen.
          Ausgabe ist reiner Text; das Frontend setzt ihn ausschließlich per textContent.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

_BR = re.compile(r"<\s*(br|/p|/div|/li)\s*/?\s*>", re.I)
_WS = re.compile(r"\s+")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def clean_text(value: str | None, max_len: int = 600) -> str:
    if not value:
        return ""
    value = _BR.sub(" ", str(value))
    parser = _Text()
    parser.feed(value)
    parser.close()
    text = _CTRL.sub("", "".join(parser.parts))
    text = _WS.sub(" ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text
