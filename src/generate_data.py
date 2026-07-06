"""
Phase 1 — Synthetic data generator.

Builds two datasets that SHOULD reconcile (a general ledger and a bank feed),
deliberately injects realistic breaks, and writes messy free-text remittance
notes (some as PDF) for the LLM to read later.

Outputs (see config.py):
    data/ledger.csv
    data/bank_feed.csv
    data/notes/*.txt | *.pdf
    data/ground_truth.csv   (the seeded breaks, so the pipeline can be scored)

Break types to seed:
    missing-in-bank, missing-in-ledger, amount-mismatch, duplicate, reversal

Status: TODO — implemented in Phase 1.
"""

from __future__ import annotations

import config  # noqa: F401  (paths live here)


def main() -> None:
    raise NotImplementedError("Phase 1 — run the Phase 1 prompt to build this.")


if __name__ == "__main__":
    main()
