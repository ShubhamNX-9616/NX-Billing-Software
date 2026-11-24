"""
Back up billing.db, tailoring.db and the locally stored photos into one zip.

The databases are copied with SQLite's online backup API, so this is safe to
run while the app is serving requests (a plain file copy of a WAL database can
capture a half-written state). Each copy is integrity-checked before it is
zipped. Photos stored on Cloudflare R2 are not included — R2 holds those.

Usage (from the project root):
    python scripts/backup.py
    python scripts/backup.py --dest "D:/OneDrive/shubham-backups" --keep 30

Put --dest on a different drive (or a synced folder) than the app: a backup on
the same disk does not survive that disk failing. BACKUP_DIR in .env is used
when --dest is not given; otherwise ./backups.

Restore: stop the app, unzip the backup, and copy billing.db and
tailoring.db over the live ones (delete any billing.db-wal / -shm /
tailoring.db-wal / -shm beside them first) and the uploads/ folder back.
"""
import argparse
import os
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "shubham-backup-"


def copy_database(src_path, dst_path):
    """Consistent copy of a live SQLite file; raises if the copy is damaged."""
    # sqlite3.connect() silently creates an empty DB for a wrong path, which
    # would "back up" nothing and report success.
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"database not found: {src_path}")
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if result != "ok":
        raise RuntimeError(f"integrity check failed for {src_path}: {result}")


def prune(dest, keep):
    """Delete the oldest backups so only the newest `keep` remain."""
    names = sorted(n for n in os.listdir(dest)
                   if n.startswith(PREFIX) and n.endswith(".zip"))
    removed = names[:-keep] if keep > 0 else []
    for n in removed:
        os.remove(os.path.join(dest, n))
    return removed


def run_backup(databases, uploads_dir, dest, keep=14, now=None):
    """databases: {name_in_zip: path}. Returns the path of the new zip."""
    os.makedirs(dest, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    final = os.path.join(dest, f"{PREFIX}{stamp}.zip")
    partial = final + ".part"      # never leave a half-written .zip behind

    with tempfile.TemporaryDirectory() as tmp:
        copies = {}
        for name, path in databases.items():
            copies[name] = os.path.join(tmp, name)
            copy_database(path, copies[name])

        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
                for name, copy in copies.items():
                    z.write(copy, name)
                if uploads_dir and os.path.isdir(uploads_dir):
                    for folder, _, files in os.walk(uploads_dir):
                        for f in files:
                            full = os.path.join(folder, f)
                            rel = os.path.relpath(full, os.path.dirname(uploads_dir))
                            z.write(full, rel)
            os.replace(partial, final)
        finally:
            if os.path.exists(partial):
                os.remove(partial)

    prune(dest, keep)
    return final


def _default_dest():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    except ImportError:
        pass
    return os.environ.get("BACKUP_DIR") or os.path.join(PROJECT_ROOT, "backups")


def main():
    sys.path.insert(0, PROJECT_ROOT)
    from db.connection import DB_PATH
    from db.tailoring import TAILORING_DB_PATH

    p = argparse.ArgumentParser(description="Back up databases and photos.")
    p.add_argument("--dest", default=None, help="folder for backup zips")
    p.add_argument("--keep", type=int, default=14,
                   help="how many recent backups to keep (default 14)")
    args = p.parse_args()

    try:
        out = run_backup(
            {"billing.db": DB_PATH, "tailoring.db": TAILORING_DB_PATH},
            os.path.join(PROJECT_ROOT, "uploads"),
            os.path.abspath(args.dest or _default_dest()),
            keep=args.keep,
        )
    except Exception as e:
        print(f"BACKUP FAILED: {e}", file=sys.stderr)
        return 1
    print(f"Backup written: {out} ({os.path.getsize(out) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
