"""
Phase 3 - The Python/pandas reconciliation pipeline.

The same reconciliation as the SQL (Phase 2), done in pandas so it runs on files
without a database, cleans the data, produces a structured multi-sheet Excel
exceptions report, writes the breaks back to SQLite, and logs the whole run.

Production habits (this is what separates a script from a notebook):
    - functions with single responsibilities
    - logging to a file AND the console
    - config-driven paths (config.py) - no hard-coded strings
    - try/except around the run with a non-zero exit on failure
    - idempotent: safe to re-run, outputs are overwritten

Buckets produced (via pd.merge(..., how='outer', indicator=True)):
    matched, missing-in-bank (ledger-only), missing-in-ledger (bank-only),
    amount-mismatch, duplicate  -  reversals are excluded before merging.

Run:   python -m src.reconcile        (or  python src/reconcile.py)
Out:   reports/exceptions_report.xlsx, reports/reconcile.log,
       table `exceptions` in data/finrecon.db
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

LOG_FILE = config.REPORTS_DIR / "reconcile.log"
TOL = config.AMOUNT_TOLERANCE

log = logging.getLogger("finrecon.reconcile")


# ----------------------------------------------------------------------
def setup_logging() -> None:
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(ch)


# ----------------------------------------------------------------------
def load_sources() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not config.LEDGER_CSV.exists() or not config.BANK_FEED_CSV.exists():
        raise FileNotFoundError(
            "ledger.csv / bank_feed.csv not found - run src/generate_data.py first.")
    ledger = pd.read_csv(config.LEDGER_CSV)
    bank = pd.read_csv(config.BANK_FEED_CSV)
    log.info("Loaded ledger=%d rows, bank_feed=%d rows", len(ledger), len(bank))
    return ledger, bank


def clean(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Trim/upper-case text, coerce dtypes. Does NOT drop bank duplicates -
    those are a real break we must detect, not noise to silently remove."""
    df = df.copy()
    for col in ("reference", "account", "currency"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.upper()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["txn_date"] = pd.to_datetime(df["txn_date"], errors="coerce").dt.date
    before = len(df)
    df = df.dropna(subset=["reference", "amount"])
    if len(df) != before:
        log.warning("%s: dropped %d rows with null reference/amount", name, before - len(df))
    log.info("Cleaned %s: %d rows", name, len(df))
    return df


def find_reversals(bank: pd.DataFrame) -> set[str]:
    """References whose bank rows net to ~0 across 2+ entries = reversals/retries."""
    grp = bank.groupby("reference")["amount"].agg(["sum", "count"])
    refs = set(grp[(grp["sum"].abs() < TOL) & (grp["count"] >= 2)].index)
    log.info("Identified %d reversal reference(s) to exclude", len(refs))
    return refs


def summarise_bank(bank: pd.DataFrame, reversal_refs: set[str]) -> pd.DataFrame:
    """Collapse the bank feed to one row per reference, reversals removed.
    bank_rows>1 marks duplicates; bank_amount is the per-line amount (MIN)."""
    clean_bank = bank[~bank["reference"].isin(reversal_refs)]
    summary = (clean_bank.groupby("reference")
               .agg(bank_rows=("amount", "size"),
                    bank_amount=("amount", "min"),
                    bank_sum=("amount", "sum"),
                    bank_currency=("currency", "max"))
               .reset_index())
    return summary


def reconcile(ledger: pd.DataFrame, bank_summary: pd.DataFrame) -> pd.DataFrame:
    """Outer-merge on reference (indicator=True) and classify every reference."""
    led = ledger.rename(columns={"amount": "ledger_amount",
                                 "currency": "ledger_currency"})[
        ["reference", "ledger_amount", "ledger_currency", "txn_date"]]

    m = led.merge(bank_summary, on="reference", how="outer", indicator=True)

    both = m["_merge"] == "both"
    is_missing_bank = m["_merge"] == "left_only"
    is_missing_ledger = m["_merge"] == "right_only"
    is_duplicate = both & (m["bank_rows"] > 1)
    is_mismatch = both & (m["bank_rows"] == 1) & \
        ((m["ledger_amount"] - m["bank_amount"]).abs() > TOL)

    m["break_type"] = np.select(
        [is_missing_bank, is_missing_ledger, is_duplicate, is_mismatch],
        ["missing-in-bank", "missing-in-ledger", "duplicate", "amount-mismatch"],
        default="matched")

    m["amount_diff"] = np.where(
        both, (m["bank_amount"] - m["ledger_amount"]).round(2), np.nan)

    m["value_at_risk"] = np.select(
        [is_missing_bank, is_missing_ledger, is_duplicate, is_mismatch],
        [m["ledger_amount"], m["bank_amount"], m["bank_amount"],
         (m["bank_amount"] - m["ledger_amount"]).abs()],
        default=0.0).round(2)

    m["currency"] = m["ledger_currency"].fillna(m["bank_currency"])
    return m


def build_buckets(recon: pd.DataFrame) -> dict[str, pd.DataFrame]:
    cols = ["reference", "break_type", "ledger_amount", "bank_amount",
            "amount_diff", "value_at_risk", "currency", "txn_date", "bank_rows"]
    view = recon[cols]
    breaks = view[view["break_type"] != "matched"].sort_values(
        ["break_type", "reference"]).reset_index(drop=True)
    return {
        "All_breaks": breaks,
        "Missing_in_bank": breaks[breaks.break_type == "missing-in-bank"],
        "Missing_in_ledger": breaks[breaks.break_type == "missing-in-ledger"],
        "Amount_mismatch": breaks[breaks.break_type == "amount-mismatch"],
        "Duplicates": breaks[breaks.break_type == "duplicate"],
        "Matched": view[view.break_type == "matched"],
    }


def build_summary(recon: pd.DataFrame, ledger_total: int, n_reversals: int) -> pd.DataFrame:
    breaks = recon[recon.break_type != "matched"]
    by_type = (breaks.groupby("break_type")
               .agg(count=("reference", "size"),
                    value_at_risk=("value_at_risk", "sum"))
               .round(2).reset_index())
    matched = int((recon.break_type == "matched").sum())
    meta = pd.DataFrame([
        {"break_type": "TOTAL breaks", "count": len(breaks),
         "value_at_risk": round(breaks.value_at_risk.sum(), 2)},
        {"break_type": "matched", "count": matched, "value_at_risk": 0.0},
        {"break_type": "match_rate_pct", "count": round(100.0 * matched / ledger_total, 2),
         "value_at_risk": None},
        {"break_type": "reversals_excluded", "count": n_reversals, "value_at_risk": None},
    ])
    return pd.concat([by_type, meta], ignore_index=True)


def reversals_sheet(bank: pd.DataFrame, reversal_refs: set[str]) -> pd.DataFrame:
    rev = bank[bank["reference"].isin(reversal_refs)]
    return (rev.groupby("reference")
            .agg(rows=("amount", "size"), net_amount=("amount", "sum"),
                 currency=("currency", "max"))
            .reset_index())


def write_excel(buckets: dict[str, pd.DataFrame], summary: pd.DataFrame,
                reversals: pd.DataFrame) -> None:
    out = config.EXCEPTIONS_REPORT
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        summary.to_excel(xl, sheet_name="Summary", index=False)
        for name, df in buckets.items():
            df.to_excel(xl, sheet_name=name[:31], index=False)
        reversals.to_excel(xl, sheet_name="Reversals_excluded", index=False)
    log.info("Wrote Excel report -> %s (%d sheets)", out.name, len(buckets) + 2)


def write_db(breaks: pd.DataFrame) -> None:
    engine = create_engine(config.DB_URL)
    with engine.begin() as conn:
        breaks.to_sql("exceptions", conn, if_exists="replace", index=False)
    log.info("Wrote %d breaks back to table `exceptions`", len(breaks))


def validate(recon: pd.DataFrame) -> bool:
    """Score detected breaks against the seeded ground truth."""
    if not config.GROUND_TRUTH_CSV.exists():
        log.warning("No ground_truth.csv - skipping validation.")
        return True
    gt = pd.read_csv(config.GROUND_TRUTH_CSV)
    expected = gt[gt.break_type != "reversal"]
    det = recon[recon.break_type != "matched"]
    ok = True
    for t in ["amount-mismatch", "missing-in-bank", "missing-in-ledger", "duplicate"]:
        exp = set(expected[expected.break_type == t].reference)
        got = set(det[det.break_type == t].reference)
        match = exp == got
        ok &= match
        log.info("validate %-18s expected=%d detected=%d %s",
                 t, len(exp), len(got), "OK" if match else "MISMATCH")
    return ok


# ----------------------------------------------------------------------
def main() -> int:
    setup_logging()
    log.info("=== Phase 3 reconciliation run START ===")
    try:
        ledger, bank = load_sources()
        ledger = clean(ledger, "ledger")
        bank = clean(bank, "bank_feed")

        reversal_refs = find_reversals(bank)
        bank_summary = summarise_bank(bank, reversal_refs)
        recon = reconcile(ledger, bank_summary)

        buckets = build_buckets(recon)
        summary = build_summary(recon, ledger_total=len(ledger),
                                n_reversals=len(reversal_refs))
        write_excel(buckets, summary, reversals_sheet(bank, reversal_refs))
        write_db(buckets["All_breaks"])

        n_breaks = len(buckets["All_breaks"])
        match_rate = 100.0 * (recon.break_type == "matched").sum() / len(ledger)
        log.info("Breaks=%d | match_rate=%.2f%% | value_at_risk=%.2f",
                 n_breaks, match_rate, buckets["All_breaks"].value_at_risk.sum())

        ok = validate(recon)
        log.info("Validation: %s", "PASS" if ok else "FAIL")
        log.info("=== Phase 3 reconciliation run END ===")
        return 0 if ok else 1
    except Exception:  # noqa: BLE001 - top-level guard, log full traceback
        log.exception("Reconciliation FAILED")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
