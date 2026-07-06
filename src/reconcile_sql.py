"""
Phase 2 (runner) - Execute the SQL reconciliation and score it.

Steps:
    1. Load the CSVs into SQLite (via src/load_db.py).
    2. Run sql/reconciliation.sql to build the reversals/bank_summary views,
       the recon_result table and the breaks view.
    3. Print the three summary queries (breaks by type, match rate, reversals).
    4. Validate the detected breaks against data/ground_truth.csv - the
       Phase 2 "definition of done": SQL finds all seeded break types correctly.

Run:   python src/reconcile_sql.py
Exit code is non-zero if the reconciliation does not match ground truth.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import load_db  # noqa: E402

SQL_FILE = config.SQL_DIR / "reconciliation.sql"


def run_sql() -> None:
    sql = SQL_FILE.read_text(encoding="utf-8")
    con = sqlite3.connect(config.DB_PATH)
    try:
        con.executescript(sql)
        con.commit()
    finally:
        con.close()


def _q(sql: str) -> pd.DataFrame:
    con = sqlite3.connect(config.DB_PATH)
    try:
        return pd.read_sql_query(sql, con)
    finally:
        con.close()


def print_summaries() -> None:
    print("\n=== Breaks by type (value at risk) ===")
    print(_q("""
        SELECT break_type,
               COUNT(*)                     AS n,
               ROUND(SUM(value_at_risk), 2) AS value_at_risk
        FROM breaks GROUP BY break_type ORDER BY n DESC;
    """).to_string(index=False))

    print("\n=== Match rate ===")
    print(_q("""
        SELECT
          (SELECT COUNT(*) FROM recon_result WHERE break_type='matched') AS matched,
          (SELECT COUNT(*) FROM ledger)                                  AS ledger_total,
          ROUND(100.0 * (SELECT COUNT(*) FROM recon_result WHERE break_type='matched')
                       / (SELECT COUNT(*) FROM ledger), 2)               AS match_rate_pct;
    """).to_string(index=False))

    print("\n=== Reversals excluded ===")
    print(_q("SELECT COUNT(*) AS reversal_refs_excluded FROM reversals;").to_string(index=False))


def validate_against_ground_truth() -> bool:
    """Compare detected breaks to the seeded truth. Returns True if perfect."""
    if not config.GROUND_TRUTH_CSV.exists():
        print("\n=== Validation skipped (no ground_truth.csv - provided data) ===")
        return True
    gt = pd.read_csv(config.GROUND_TRUTH_CSV)[["reference", "break_type"]]
    detected = _q("SELECT reference, break_type FROM breaks")

    gt_map = dict(zip(gt.reference, gt.break_type))
    det_map = dict(zip(detected.reference, detected.break_type))

    # Reversals are correctly EXCLUDED, so they should not appear in breaks.
    expected_breaks = {r: t for r, t in gt_map.items() if t != "reversal"}
    reversal_refs = {r for r, t in gt_map.items() if t == "reversal"}

    rev_view = set(_q("SELECT reference FROM reversals").reference)

    print("\n=== Validation vs ground truth ===")
    types = ["amount-mismatch", "missing-in-bank", "missing-in-ledger", "duplicate"]
    all_ok = True
    header = f"{'break_type':<20}{'expected':>10}{'detected':>10}{'correct':>10}"
    print(header)
    for t in types:
        exp = {r for r, tt in expected_breaks.items() if tt == t}
        det = {r for r, tt in det_map.items() if tt == t}
        correct = exp & det
        ok = (exp == det)
        all_ok &= ok
        print(f"{t:<20}{len(exp):>10}{len(det):>10}{len(correct):>10}"
              f"{'' if ok else '   <-- MISMATCH'}")

    # False positives: anything flagged that ground truth says is fine.
    false_pos = {r: det_map[r] for r in det_map
                 if r not in expected_breaks}
    # Reversal handling: excluded from breaks AND recognised by the view.
    rev_ok = (reversal_refs == rev_view) and reversal_refs.isdisjoint(set(det_map))

    print(f"\nreversals seeded={len(reversal_refs)}  "
          f"detected-by-view={len(rev_view)}  "
          f"leaked-into-breaks={len(reversal_refs & set(det_map))}  "
          f"-> {'OK' if rev_ok else 'FAIL'}")
    if false_pos:
        all_ok = False
        print(f"FALSE POSITIVES (flagged but clean): {list(false_pos.items())[:10]}")

    all_ok &= rev_ok
    print("\nRESULT:", "PASS - SQL matches ground truth exactly."
          if all_ok else "FAIL - see mismatches above.")
    return all_ok


def main() -> int:
    load_db.load()
    run_sql()
    print_summaries()
    ok = validate_against_ground_truth()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
