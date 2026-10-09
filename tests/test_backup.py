import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import backup  # noqa: E402
import pytest  # noqa: E402


def test_backup_is_consistent_and_rotates(settings, storage, tmp_path):
    from test_sanitize_registry_db import ev
    storage.replace_snapshot("autobahn", [ev("a")])
    out = tmp_path / "bk"
    files = []
    for i in range(4):
        (out).mkdir(exist_ok=True)
        files.append(backup.backup_once(settings.db_path, out, keep=2))
        (out / files[-1].name).rename(out / f"osint-2026010{i}T000000Z.sqlite")  # eindeutige, aufsteigende Namen
    assert len(list(out.glob("osint-*.sqlite"))) == 2
    newest = sorted(out.glob("osint-*.sqlite"))[-1]
    assert sqlite3.connect(newest).execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_backup_missing_db_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup.backup_once(tmp_path / "nix.sqlite", tmp_path / "bk", 3)
