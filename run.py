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

import os
import sys
from pathlib import Path

# ── Bootstrap: make `python run.py` work from ANY interpreter ───────────
# The project's dependencies live in ./.venv. If you launch this with a Python
# that doesn't have them (e.g. base conda), we transparently re-exec using the
# venv's interpreter so you don't have to remember to activate it.
ROOT = Path(__file__).resolve().parent
_VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
try:
    import pandas  # noqa: F401  - just probing that deps are installed
except ModuleNotFoundError:
    # Re-launch under the venv interpreter. We use subprocess (not os.execv)
    # because on Windows execv detaches the child's stdout and returns early.
    if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
        import subprocess
        print(f"[run] using project venv: {_VENV_PY}", flush=True)
        sys.exit(subprocess.run([str(_VENV_PY), str(ROOT / "run.py"), *sys.argv[1:]]).returncode)
    print(
        "\n[run] This Python has no project dependencies installed.\n"
        "      Set up the virtual environment once:\n\n"
        "        python -m venv .venv\n"
        "        .venv\\Scripts\\python -m pip install -r requirements.txt\n\n"
        "      Then run:  python run.py   (it will use the venv automatically)\n"
    )
    raise SystemExit(1)

import pandas as pd  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from src import (evaluate_prompts, export_powerbi, generate_data,  # noqa: E402
                 genai, governance, llm, make_dashboard, reconcile, reconcile_sql)


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

    # The prompt-eval harness makes ~66 LLM calls, so it's opt-in to keep the
    # default run fast. Enable with:  python run.py --eval
    if "--eval" in sys.argv:
        print("\n-- prompt evaluation harness --")
        evaluate_prompts.main()
    else:
        print("\n(skipping prompt-eval harness; run `python run.py --eval` for it)")

    banner("PHASE 5  Governance & controls")
    governance.main()

    banner("PHASE 7  Reporting (Power BI dataset + local HTML dashboard)")
    export_powerbi.main()
    make_dashboard.main()

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
    print(f"  dashboard (open me)      : reports/dashboard.html")
    print("  controls                 : PII masking, output validation, "
          "audit log, human-in-the-loop")
    print("\n  Rules for the math - AI for the language - human for the decisions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
