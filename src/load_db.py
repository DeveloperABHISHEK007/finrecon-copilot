"""
Phase 2 (loader) - Load the CSVs into SQLite with SQLAlchemy.

Reads data/ledger.csv and data/bank_feed.csv and writes them as tables
`ledger` and `bank_feed` into data/finrecon.db. Reusable by Phase 3.

Run:   python src/load_db.py
Idempotent: tables are replaced on each run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def load() -> None:
    if not config.LEDGER_CSV.exists() or not config.BANK_FEED_CSV.exists():
        raise FileNotFoundError(
            "Missing ledger.csv / bank_feed.csv - run src/generate_data.py first.")

    engine = create_engine(config.DB_URL)
    ledger = pd.read_csv(config.LEDGER_CSV)
    bank = pd.read_csv(config.BANK_FEED_CSV)

    with engine.begin() as conn:
        ledger.to_sql("ledger", conn, if_exists="replace", index=False)
        bank.to_sql("bank_feed", conn, if_exists="replace", index=False)
        # Helpful indexes for the join on reference.
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ledger_ref ON ledger(reference)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bank_ref ON bank_feed(reference)"))

    print(f"[load_db] ledger    -> {len(ledger):>5} rows")
    print(f"[load_db] bank_feed -> {len(bank):>5} rows")
    print(f"[load_db] database  -> {config.DB_PATH}")


if __name__ == "__main__":
    load()
