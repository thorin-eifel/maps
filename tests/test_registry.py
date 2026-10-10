"""Tests für das Quellenregister: Client-Quellen (art=client) laufen nicht im Sammler und brauchen keinen Collector."""
from __future__ import annotations

import pytest


def test_client_quelle_braucht_keinen_collector_und_laeuft_nicht_im_sammler():
    from app.registry import Registry, SourceEntry
    base = dict(name="x", betreiber="b", url="https://example.org", lizenz="l", namensnennung="n", intervall=60, ratenlimit="r",
                geo_bezug="g", datenschutz_risiko="mittel", zuletzt_geprüft="2026-10-10")
    client = SourceEntry(id="c", art="client", **base)
    coll = SourceEntry(id="k", collector="dwd_warnungen", **base)
    reg = Registry([client, coll])
    assert [e.id for e in reg.active()] == ["k"]
    with pytest.raises(ValueError, match="collector fehlt"):
        SourceEntry(id="z", **base)
