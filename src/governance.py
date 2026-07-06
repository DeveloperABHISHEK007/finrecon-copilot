"""
Phase 5 — Governance & controls (the differentiator).

The bank-grade wrapper that turns a clever script into something a regulated
finance team can trust:

    1. mask_pii(text)        -> strip names / account numbers BEFORE the LLM
    2. validate_output(obj)  -> JSON well-formed? amount numeric & in range?
                                category in ALLOWED_CATEGORIES? else quarantine
    3. audit_log(run_meta)   -> inputs, row counts, model version, prompts,
                                outputs, timestamps — one record per run
    4. needs_human(break_)   -> flag high-value / low-confidence breaks for the
                                maker-checker approval step

Status: TODO — implemented in Phase 5.
"""

from __future__ import annotations

import config  # noqa: F401


def main() -> None:
    raise NotImplementedError("Phase 5 — run the Phase 5 prompt to build this.")


if __name__ == "__main__":
    main()
