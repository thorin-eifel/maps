"""Redaktionelle Auswahl auf einen Ebenenbaum anwenden (gemeinsam für build_lgb_katalog.py und build_landesdaten_katalog.py).

Zweck:  tools/katalog_auswahl.json nennt je Menü die Ebenen (Dienst + Ebenenname), die im Menü stehen. Hier: laden, prüfen, einen Ebenenbaum
        auf die gewählten Namen kürzen (Ordner ohne Rest entfallen) und die Titel von Mojibake befreien (manche Server liefern UTF-8, das als
        Latin-1 gelesen wurde: "LangzeitzÃ¤hlstellen").
Test:   tests/test_katalog_auswahl.py
"""
from __future__ import annotations

import json
from pathlib import Path

AUSWAHL = Path(__file__).resolve().parent / "katalog_auswahl.json"


def lade(menue: str, pfad: Path = AUSWAHL) -> list[dict]:
    """Einträge eines Menüs ('lgb' oder 'landesdaten'); Fehler bei doppelten oder unvollständigen Einträgen."""
    eintraege = json.loads(pfad.read_text(encoding="utf-8"))[menue]
    gesehen = set()
    for e in eintraege:
        if not e.get("dienst") or not e.get("ebene"):
            raise ValueError(f"Auswahl {menue}: Eintrag ohne dienst/ebene: {e}")
        k = (e["dienst"], e["ebene"])
        if k in gesehen:
            raise ValueError(f"Auswahl {menue}: doppelt: {k}")
        gesehen.add(k)
    return eintraege


def repariere_titel(t: str) -> str:
    """'LangzeitzÃ¤hlstellen' → 'Langzeitzählstellen'; was sich nicht verlustfrei zurückrechnen lässt, bleibt."""
    if "Ã" not in t and "â" not in t:
        return t
    try:
        return t.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return t


def kuerze(knoten: list[dict], namen: set[str]) -> list[dict]:
    """Baum auf die Ebenen mit Namen aus `namen` kürzen. Ordner ohne verbleibende Kinder entfallen."""
    out = []
    for n in knoten:
        kids = kuerze(n.get("children", []), namen)
        if n.get("name") in namen or kids:
            m = {k: v for k, v in n.items() if k != "children"}
            m["title"] = repariere_titel(m.get("title", ""))
            if m.get("name") not in namen:
                m.pop("name", None)   # Ordner behält keinen eigenen Namen, wenn er selbst nicht gewählt ist
                for k in ("abstract", "min_scale", "max_scale", "legend", "info"):
                    m.pop(k, None)
            if "abstract" in m:
                m["abstract"] = repariere_titel(m["abstract"])
            if kids:
                m["children"] = kids
            out.append(m)
    return out


def namen_im_baum(knoten: list[dict]) -> set[str]:
    s = set()
    for n in knoten:
        if n.get("name"):
            s.add(n["name"])
        s |= namen_im_baum(n.get("children", []))
    return s
