#!/usr/bin/env python3
"""Create the SQLite logging schema. Safe to re-run (idempotent)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import db, config

if __name__ == "__main__":
    db.init_db()
    print(f"Initialized DB at {config.DB_PATH}")
