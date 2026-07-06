"""
Phase 3 — The Python/pandas reconciliation pipeline.

Reads the ledger + bank feed, cleans them, reconciles with an outer merge
(indicator=True) into matched / ledger-only / bank-only / amount-mismatch
buckets, writes a multi-sheet Excel exceptions report, and logs the run.

Production habits to add in Phase 3: functions, file logging, config-driven
paths, try/except, idempotent (safe) re-runs.

Outputs (see config.py):
    reports/exceptions_report.xlsx
    reports/audit.log

Status: TODO — implemented in Phase 3.
"""

from __future__ import annotations

import config  # noqa: F401


def main() -> None:
    raise NotImplementedError("Phase 3 — run the Phase 3 prompt to build this.")


if __name__ == "__main__":
    main()
