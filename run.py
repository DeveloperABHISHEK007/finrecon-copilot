"""
FinRecon Copilot - end-to-end runner (Phases 1-5).

Runs the whole pipeline in order and prints a consolidated scoreboard:
    1. generate synthetic data        (src/generate_data.py)
    2. SQL reconciliation + validate   (src/reconcile_sql.py)
    3. pandas pipeline + Excel report  (src/reconcile.py)
    4. GenAI layer + prompt eval       (src/genai.py, src/evaluate_prompts.py)
    5. governance & controls           (src/governance.py)

Usage:   python run.py
Phase 4/5 call the LLM if a key is set in .env; otherwise they run offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from src import (evaluate_prompts, generate_data, genai, governance,  # noqa: E402
                 llm, reconcile, reconcile_sql)


def banner(title: str) -> None:
    print("\n" + "=" * 74)
    print(f"  {title}")
    print("=" * 74)


def main() -> int:
    banner("PHASE 1  Generate synthetic data")
    generate_data.main()

    banner("PHASE 2  SQL reconciliation (validated vs ground truth)")
    reconcile_sql.main()

    banner("PHASE 3  Python/pandas pipeline (+ multi-sheet Excel report)")
    reconcile.main()

    banner("PHASE 4  GenAI layer (classify / extract / summarise)")
    print(f"provider: {llm.provider_label()} | live: {llm.available()}\n")
    engine = create_engine(config.DB_URL)
    breaks = pd.read_sql(
        "SELECT reference, break_type, value_at_risk FROM exceptions "
        "ORDER BY value_at_risk DESC", engine)
    if llm.available():
        note = ("ref REF-000113 keyed wrong, should be 151,881.14 not shown, "
                "typo, 2026-06-20")
        print("classify:", genai.classify_note(note))
        print("extract :", genai.extract_fields(note))
        print("\nmanager end-of-day summary:")
        print(" ", genai.summarise_day(breaks.to_dict("records")).replace("\n", "\n  "))
    else:
        print("(offline - add GROQ_API_KEY to .env for live LLM calls)")
    print("\n-- prompt evaluation harness --")
    evaluate_prompts.main()

    banner("PHASE 5  Governance & controls")
    governance.main()

    # ── consolidated scoreboard ────────────────────────────────────────
    banner("SCOREBOARD  FinRecon Copilot end-to-end")
    n_breaks = int(len(breaks))
    var = float(breaks["value_at_risk"].sum())
    matched = pd.read_sql(
        "SELECT COUNT(*) c FROM recon_result WHERE break_type='matched'", engine).c[0]
    total = pd.read_sql("SELECT COUNT(*) c FROM ledger", engine).c[0]
    print(f"  ledger rows              : {total}")
    print(f"  breaks found             : {n_breaks}")
    print(f"  match rate               : {100.0 * matched / total:.2f}%")
    print(f"  value at risk surfaced   : {var:,.2f}")
    print(f"  reversals excluded       : "
          f"{pd.read_sql('SELECT COUNT(*) c FROM reversals', engine).c[0]}")
    print(f"  LLM provider             : {llm.provider_label()} "
          f"(live={llm.available()})")
    print(f"  artefacts                : reports/exceptions_report.xlsx, "
          f"reports/audit.log, reports/approvals_queue.csv")
    print("  controls                 : PII masking, output validation, "
          "audit log, human-in-the-loop")
    print("\n  Rules for the math - AI for the language - human for the decisions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
