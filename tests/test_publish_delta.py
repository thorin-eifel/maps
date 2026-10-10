"""Inkrementeller Upload: Plan aus Manifest und Stand, Reihenfolge, Herzschlag, Skript-Trockenlauf."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import publish_delta as pd  # noqa: E402
from app import export  # noqa: E402
from test_export_cells import mk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def manifest(**files):
    return {"generated_at": "t", "files": files}


def f(h, upload="on_change", **kw):
    return {"bytes": 10, "content_hash": h, "upload": upload, **kw}


def test_first_run_uploads_everything_with_manifest_last():
    m = manifest(**{"z/1_1/events.json": f("a"), "start.json": f("s", "always"), "status.json": f("x", "always")})
    p = pd.plan(m, {"files": {}})
    assert set(p) == {"z/1_1/events.json", "start.json", "status.json", "manifest.json"}
    assert p[-1] == "manifest.json" and p[-2] == "start.json"


def test_unchanged_run_sends_only_heartbeat_files():
    m = manifest(**{"z/1_1/events.json": f("a"), "z/1_2/events.json": f("b"), "start.json": f("s", "always"), "status.json": f("x", "always")})
    st = pd.commit(m, {"files": {}}, pd.plan(m, {"files": {}}), now=1000)
    assert pd.plan(m, st, now=1100) == ["status.json", "start.json", "manifest.json"]


def test_only_changed_cell_is_added():
    m = manifest(**{"z/1_1/events.json": f("a"), "z/1_2/events.json": f("b"), "start.json": f("s", "always")})
    st = pd.commit(m, {"files": {}}, pd.plan(m, {"files": {}}), now=1000)
    m2 = manifest(**{"z/1_1/events.json": f("a"), "z/1_2/events.json": f("B"), "start.json": f("s2", "always")})
    assert pd.plan(m2, st, now=1100) == ["z/1_2/events.json", "start.json", "manifest.json"]


def test_flat_file_is_refreshed_after_max_age_even_if_unchanged():
    m = manifest(**{"suche.json": f("a", max_age_s=1800), "start.json": f("s", "always")})
    st = pd.commit(m, {"files": {}}, pd.plan(m, {"files": {}}), now=1000)
    assert "suche.json" not in pd.plan(m, st, now=1000 + 1799)
    assert "suche.json" in pd.plan(m, st, now=1000 + 1801)


def test_failed_upload_is_retried_because_commit_never_ran():
    m = manifest(**{"z/1_1/events.json": f("a"), "start.json": f("s", "always")})
    assert "z/1_1/events.json" in pd.plan(m, {"files": {}})
    assert "z/1_1/events.json" in pd.plan(m, {"files": {}})          # kein commit → gleicher Plan


def test_cli_roundtrip_with_real_export(storage, registry, tmp_path, capsys):
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85]), mk("far", [8.2, 49.2])])
    data = tmp_path / "data"
    export.run_export(storage, registry, data)
    plan_file = tmp_path / "plan.txt"
    assert pd.main(["plan", "--data", str(data), "--out", str(plan_file)]) == 0
    first = plan_file.read_text().split()
    assert "z/12_99/events.json" in first and first[-1] == "manifest.json" and len(first) > 20
    assert pd.main(["commit", "--data", str(data), "--plan", str(plan_file)]) == 0
    export.run_export(storage, registry, data)                       # keine Datenänderung
    assert pd.main(["plan", "--data", str(data), "--out", str(plan_file)]) == 0
    second = plan_file.read_text().split()
    assert len(second) <= 6 and not any(p.startswith("z/") for p in second), second
    size = sum((data / p).stat().st_size for p in second)
    assert size < 400 * 1024


def test_missing_manifest_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit) as e:
        pd.main(["plan", "--data", str(tmp_path)])
    assert "manifest.json" in str(e.value)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash fehlt")
def test_publish_sh_delta_dry_run_lists_mkdir_and_puts_manifest_last(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85])])
    root = tmp_path / "proj"
    (root / "deploy").mkdir(parents=True)
    (root / "tools").mkdir()
    shutil.copy(ROOT / "deploy/publish.sh", root / "deploy/publish.sh")
    shutil.copy(ROOT / "tools/publish_delta.py", root / "tools/publish_delta.py")
    export.run_export(storage, registry, root / "web" / "data")
    env = {**os.environ, "IONOS_SFTP_HOST": "h", "IONOS_SFTP_USER": "u", "IONOS_SFTP_PASSWORD": "x", "IONOS_REMOTE_DIR": "/lagebild"}
    r = subprocess.run(["bash", str(root / "deploy/publish.sh"), "--delta", "--dry-run"], capture_output=True, text=True, env=env, cwd=root)
    assert r.returncode == 0, r.stderr
    lines = [l for l in r.stdout.splitlines() if l.startswith(("put", "mkdir"))]
    assert "mkdir -p -f /lagebild/data/z/12_99" in lines
    assert "put -O /lagebild/data/z/12_99 web/data/z/12_99/events.json" in lines
    assert lines[-1] == "put -O /lagebild/data web/data/manifest.json"
    assert not (root / "web/data/.published.json").exists()           # Trockenlauf schreibt keinen Stand
