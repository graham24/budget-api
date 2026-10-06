"""Snapshots the SQLite database to ~/backups/budget/ and prunes old snapshots.
Intended to be run on a schedule (see cron setup)."""
import datetime
import sqlite3
from pathlib import Path

from models.db import db_path

# Outside the repo, next to the other ~/backups/ copies, so snapshots don't
# pile up in the working tree.
BACKUP_DIR = Path.home() / "backups" / "budget"
KEEP_DAYS = 30


def backup():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_budget_{timestamp}.db"

    # sqlite3's online backup API takes a consistent snapshot even while the
    # app or cron importer is writing — a plain file copy of a WAL-mode DB
    # can miss committed pages still sitting in the -wal file.
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    backup_path.chmod(0o600)

    # Only prune once the new snapshot exists, so a failing backup never
    # leaves us with fewer copies than before.
    cutoff = datetime.datetime.now() - datetime.timedelta(days=KEEP_DAYS)
    for old in BACKUP_DIR.glob("backup_budget_*.db"):
        if datetime.datetime.fromtimestamp(old.stat().st_mtime) < cutoff:
            old.unlink()

    print(f"{datetime.datetime.now()}: Backed up {db_path} to {backup_path}")


if __name__ == "__main__":
    backup()
