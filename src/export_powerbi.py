"""
Phase 7 (data prep) - Export a single, tidy table for Power BI.

Power BI builds fastest from one clean fact table. This joins:
    recon_result (every reference classified + value_at_risk)   [from SQLite]
    + txn_date        (from ledger, else bank feed)             -> trend / aging
    + governance      (llm_category, confidence, decision)      [governed_exceptions.csv]

Output: powerbi/finrecon_powerbi.csv  (import this in Power BI Desktop)

Run:   python -m src.export_powerbi   (after run.py has produced the DB + reports)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

OUT = config.PROJECT_ROOT / "powerbi" / "finrecon_powerbi.csv"


def build() -> pd.DataFrame:
    engine = create_engine(config.DB_URL)
    recon = pd.read_sql("SELECT * FROM recon_result", engine)

    # Attach a transaction date (ledger first, then bank) for trend/aging.
    txn = {}
    for csv in (config.LEDGER_CSV, config.BANK_FEED_CSV):
        if csv.exists():
            d = pd.read_csv(csv)[["reference", "txn_date"]]
            txn.update(dict(zip(d["reference"], d["txn_date"])))
    recon["txn_date"] = pd.to_datetime(recon["reference"].map(txn), errors="coerce")

    recon["is_break"] = (recon["break_type"] != "matched").astype(int)
    recon["month"] = recon["txn_date"].dt.to_period("M").astype(str)
    today = pd.Timestamp(date.today())
    recon["age_days"] = (today - recon["txn_date"]).dt.days

    # Join the governance decision (only breaks that carried a note were scored).
    gov_path = config.REPORTS_DIR / "governed_exceptions.csv"
    if gov_path.exists():
        gov = pd.read_csv(gov_path)[
            ["reference", "llm_category", "confidence", "decision", "reason"]]
        recon = recon.merge(gov, on="reference", how="left")
    else:
        recon[["llm_category", "confidence", "decision", "reason"]] = None

    # Fill decision: matched -> MATCHED; break w/o a scored note -> NEEDS_REVIEW.
    recon["decision"] = recon["decision"].where(recon["decision"].notna(),
        recon["break_type"].map(lambda b: "MATCHED" if b == "matched" else "NEEDS_REVIEW"))

    cols = ["reference", "break_type", "is_break", "ledger_amount", "bank_amount",
            "amount_diff", "value_at_risk", "currency", "txn_date", "month",
            "age_days", "llm_category", "confidence", "decision", "reason"]
    return recon[cols].sort_values(["is_break", "break_type", "reference"]).reset_index(drop=True)


def main() -> int:
    df = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    n_break = int(df["is_break"].sum())
    print(f"[export_powerbi] wrote {len(df)} rows -> {OUT.relative_to(config.PROJECT_ROOT)}")
    print(f"[export_powerbi] breaks={n_break}  matched={len(df) - n_break}  "
          f"value_at_risk={df['value_at_risk'].sum():,.2f}")
    print(f"[export_powerbi] decisions: {df['decision'].value_counts().to_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
