"""Ausfalltest über alle Collector (R3): Quelle antwortet mit Fehler, Zeitüberschreitung oder Unsinn.

Erwartung je Quelle: run_once() wirft nicht, schreibt nichts und löscht nichts. Eine ausgefallene Quelle darf die anderen
nicht stören (jeder Lauf ist isoliert) und keinen alten Stand wegräumen.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.collectors import load_collector_class
from conftest import make_client

MODES = {
    "http503": lambda req: httpx.Response(503, text="Service Unavailable"),
    "timeout": lambda req: (_ for _ in ()).throw(httpx.ConnectTimeout("timeout", request=req)),
    "html_statt_daten": lambda req: httpx.Response(200, text="<html><body>Wartungsarbeiten</body></html>", headers={"content-type": "text/html"}),
    "leeres_json": lambda req: httpx.Response(200, json={}),
}


def _ids(registry):
    return sorted(e.id for e in registry.entries if e.collector)


@pytest.fixture(autouse=True)
def _keys_and_no_sleep(monkeypatch):
    for k in ("TANKERKOENIG_API_KEY", "FIRMS_MAP_KEY"):
        monkeypatch.setenv(k, "k-test")
    real = asyncio.sleep

    async def fast(delay, *a, **kw):
        await real(0)
    monkeypatch.setattr(asyncio, "sleep", fast)


@pytest.mark.parametrize("mode", sorted(MODES))
async def test_every_collector_survives_outage_without_touching_data(mode, registry, storage, settings):
    bad = []
    for sid in _ids(registry):
        entry = registry.get(sid)
        client, _ = make_client(MODES[mode])
        c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
        if hasattr(c, "pause_s"):
            c.pause_s = 0
        try:
            ok = await asyncio.wait_for(c.run_once(), timeout=30)
        except Exception as exc:      # run_once darf nichts durchlassen
            bad.append(f"{sid}: {type(exc).__name__}: {exc}")
            continue
        finally:
            await client.aclose()
        if mode in ("http503", "timeout") and ok:
            bad.append(f"{sid}: meldet Erfolg trotz {mode}")
    assert not bad, "\n".join(bad)
    for t in ("events", "stations", "measurements"):    # nichts geschrieben
        assert storage._conn.execute(f"select count(*) from {t}").fetchone()[0] == 0, t


def test_outage_test_covers_all_collectors(registry):
    ids = _ids(registry)
    assert len(ids) >= 40, ids
