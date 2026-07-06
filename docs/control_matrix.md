# FinRecon Copilot — Control Matrix

The one-page answer to *"how do you use GenAI safely in a regulated finance
environment?"* Each control, why it matters, and exactly how it is implemented.

| # | Control | Risk it addresses | How it is met (code) | Evidence |
|---|---------|-------------------|----------------------|----------|
| 1 | **PII masking** | Sensitive data (account numbers, emails, names, phones) must never leave the environment inside an LLM prompt | `governance.mask_pii()` redacts account nos / emails / IBAN / phones / names **before** any text is sent to the model. The transaction *reference* is kept (non-personal, needed to match). | `pii_redactions` per item in `audit.log`; `masked_input` column in `governed_exceptions.csv` |
| 2 | **Output validation + quarantine** | An LLM can return malformed JSON, an unknown category, or an out-of-range number — untrusted output must not flow downstream | `validate_classification()` / `validate_extraction()` check JSON shape, category ∈ allowed set, confidence ∈ [0,1], amount numeric & in range, date parseable. Failures are **quarantined**, never used. | `quarantine.csv`; `valid`/`errors` fields in `audit.log` |
| 3 | **Determinism** | Finance outputs must be repeatable | All LLM calls run at **temperature 0** (`config.LLM_TEMPERATURE`). | model + params in `audit.log` |
| 4 | **Human-in-the-loop (maker-checker)** | High-value or low-confidence decisions need a human owner | `route()` sends any break that is **high-value** (≥ `HIGH_VALUE_THRESHOLD`), **low-confidence** (< `LOW_CONFIDENCE_THRESHOLD`) or **failed-validation** to a person. | `approvals_queue.csv`; `decision`/`reason` in `audit.log` |
| 5 | **Audit trail** | Every automated action must be reconstructable for audit | `AuditLog` writes append-only JSONL: timestamp, run id, model, input SHA-256, output, validity, decision — one record per item plus run start/end. | `reports/audit.log` |
| 6 | **Boundary of AI** | The LLM must not do work that has to be exact | Deterministic SQL/pandas do **all matching and math** (Phases 2–3). The LLM only reads language (Phase 4). | code separation: `reconcile.py` vs `genai.py` |
| 7 | **Change management** | Changes must be traceable | Git history with meaningful commits; **no secrets committed** (`.env`, `secrets/` git-ignored). | `git log` |

## Human-approval step (documented)

1. The reconciliation produces breaks (rules) and the LLM proposes a cause (masked input, validated output).
2. `route()` classifies each break:
   - **AUTO** — low-value *and* high-confidence *and* valid → auto-cleared, logged.
   - **HUMAN** — high-value *or* low-confidence → written to `approvals_queue.csv` for a reviewer.
   - **QUARANTINE** — output failed validation → `quarantine.csv`, excluded until fixed.
3. A reviewer works the approvals queue (in Phase 6/7 this becomes a Power Automate approval / Power App screen). Their decision is recorded — completing the maker-checker loop.

## Latest run (evidence snapshot)

- Items processed: **33** (breaks that carry a remittance note)
- PII redactions applied: **33** (account numbers)
- Decisions: **AUTO 18 / HUMAN 15 / QUARANTINE 0**
- Human reason: 15 × high-value (≥ $10,000)
- Audit records written: **35** (1 start + 33 items + 1 end)

*(Regenerate with `python -m src.governance`; figures are deterministic at temp 0.)*
