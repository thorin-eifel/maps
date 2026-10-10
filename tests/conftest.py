"""Gemeinsame Test-Helfer: Fixtures aus echten Antworten, Mock-Transport, temporäre DB."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.db import Storage  # noqa: E402
from app.registry import Registry  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def fixture(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        db_path=tmp_path / "t.sqlite", sources_path=ROOT / "sources.yaml", web_dir=ROOT / "web",
        user_agent="Landblick/test", http_timeout_s=2, http_max_attempts=3,
        breaker_threshold=5, breaker_cooldown_s=900, retention_days=30,
    )


@pytest.fixture
def storage(settings) -> Storage:
    s = Storage(settings.db_path)
    yield s
    s.close()


@pytest.fixture
def registry(settings) -> Registry:
    return Registry.load(settings.sources_path)


class Router:
    """Mock-Transport mit Zählern. Handler: (request) -> httpx.Response | dict/list (=200 JSON)."""

    def __init__(self, handler: Callable[[httpx.Request], object]) -> None:
        self.handler = handler
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        out = self.handler(request)
        return out if isinstance(out, httpx.Response) else httpx.Response(200, json=out)


def make_client(handler) -> tuple[httpx.AsyncClient, Router]:
    router = Router(handler)
    return httpx.AsyncClient(transport=httpx.MockTransport(router)), router


@pytest.fixture(autouse=True)
def _clear_collector_memory():
    """Sammler merken sich Ergebnisse im Arbeitsspeicher (NINA je Version, Autobahn-Baustellen). Tests dürfen sich nicht beeinflussen."""
    from app.collectors import autobahn, nina
    nina._CACHE.clear()
    autobahn._SLOW.clear()
    yield
