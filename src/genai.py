"""
Phase 4 — The GenAI layer (the star of the show).

For each break, the LLM reads the messy remittance note and does three things
the JD names directly, each returning strict, validated JSON:

    1. classify_cause(note)  -> TIMING | DUPLICATE | DATA_ERROR | MISSING
    2. extract_fields(note)  -> {reference, amount, date}
    3. summarise_day(breaks) -> short manager-friendly narrative

Rules that matter (say these in the interview):
    - temperature = 0 for repeatability (config.LLM_TEMPERATURE)
    - the LLM ONLY reads language — it NEVER does the reconciliation math
    - every response is validated before it is used (see governance.py)

Status: TODO — implemented in Phase 4.
"""

from __future__ import annotations

import config  # noqa: F401


def main() -> None:
    raise NotImplementedError("Phase 4 — run the Phase 4 prompt to build this.")


if __name__ == "__main__":
    main()
