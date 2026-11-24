"""Backup script: consistent DB copies, photos included, old backups pruned."""
import os
import sqlite3
import sys
import zipfile
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import backup


def make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    conn.commit()
    return conn      # left open on purpose: backup must work on a live DB


@pytest.fixture
def setup(tmp_path):
    live1 = make_db(str(tmp_path / "billing.db"), ["bill-1", "bill-2"])
    live2 = make_db(str(tmp_path / "tailoring.db"), ["order-1"])
    uploads = tmp_path / "uploads" / "tailoring"
    uploads.mkdir(parents=True)
    (uploads / "a.jpg").write_bytes(b"photo")
    yield {
        "databases": {"billing.db": str(tmp_path / "billing.db"),
                      "tailoring.db": str(tmp_path / "tailoring.db")},
        "uploads": str(tmp_path / "uploads"),
        "dest": str(tmp_path / "out"),
        "tmp": tmp_path,
    }
    live1.close()
    live2.close()


def test_backup_contains_databases_and_photos(setup):
    out = backup.run_backup(setup["databases"], setup["uploads"], setup["dest"])

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "billing.db" in names and "tailoring.db" in names
        assert any(n.replace("\\", "/") == "uploads/tailoring/a.jpg" for n in names)
        z.extract("billing.db", setup["tmp"] / "restored")

    restored = sqlite3.connect(str(setup["tmp"] / "restored" / "billing.db"))
    assert [r[0] for r in restored.execute("SELECT v FROM t ORDER BY v")] == ["bill-1", "bill-2"]
    restored.close()


def test_backup_includes_uncheckpointed_wal_data(setup):
    # Writes sitting in the -wal file (not yet in the main file) must be captured.
    live = sqlite3.connect(setup["databases"]["billing.db"])
    live.execute("INSERT INTO t VALUES ('latest')")
    live.commit()

    out = backup.run_backup(setup["databases"], setup["uploads"], setup["dest"])
    live.close()

    with zipfile.ZipFile(out) as z:
        z.extract("billing.db", setup["tmp"] / "restored")
    restored = sqlite3.connect(str(setup["tmp"] / "restored" / "billing.db"))
    assert restored.execute("SELECT COUNT(*) FROM t WHERE v='latest'").fetchone()[0] == 1
    restored.close()


def test_old_backups_are_pruned(setup):
    base = datetime(2026, 10, 1, 9, 0, 0)
    for i in range(5):
        backup.run_backup(setup["databases"], setup["uploads"], setup["dest"],
                          keep=3, now=base + timedelta(days=i))

    left = sorted(os.listdir(setup["dest"]))
    assert left == [f"shubham-backup-2026100{d}-090000.zip" for d in (3, 4, 5)]


def test_failure_leaves_no_partial_zip(setup):
    setup["databases"]["tailoring.db"] = str(setup["tmp"] / "does-not-exist.db")
    with pytest.raises(Exception):
        backup.run_backup(setup["databases"], setup["uploads"], setup["dest"])

    assert [n for n in os.listdir(setup["dest"]) if n.startswith(backup.PREFIX)] == []
