"""
Phase 5 - Governance & controls (the differentiator).

The bank-grade wrapper that turns a clever script into something a regulated
finance team can trust. Four controls, plus a runner that applies them to the
breaks end to end:

    1. mask_pii(text)               strip account numbers / emails / names / phones
                                    BEFORE any text is sent to the LLM
    2. validate_classification(obj) JSON well-formed? category allowed?
       validate_extraction(obj)     amount numeric & in range? date parseable?
                                    -> invalid output is QUARANTINED, never trusted
    3. AuditLog                     append-only JSONL: every step records inputs,
                                    counts, model, prompt hash, output, timestamp
    4. route(...)                   human-in-the-loop: high-value OR low-confidence
                                    OR failed-validation -> a person approves
                                    (the maker-checker control)

Design point for the interview: the LLM only ever sees MASKED text, its output
is never used unless it passes validation, every decision is logged, and a human
owns anything risky. That is "GenAI in a regulated environment".

Run:   python -m src.governance
Out:   reports/audit.log, reports/governed_exceptions.csv,
       reports/quarantine.csv, reports/approvals_queue.csv
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import genai, llm  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
# Control 1 - PII masking (runs BEFORE the LLM sees anything)
# ═══════════════════════════════════════════════════════════════════════
_PII_PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    # Account numbers: AC-12345678, ACC55010, ACCT 55010, ACCOUNT-1234...
    ("ACCT", re.compile(r"\bAC(?:C|CT|COUNT)?-?\s?\d{4,}\b", re.IGNORECASE)),
    # Phone: a '+' country code (7+ digits) or grouped NNN-NNN-NNNN form.
    # Deliberately strict so it does NOT swallow ISO dates or money amounts.
    ("PHONE", re.compile(r"\b(?:\+\d{7,}|\(?\d{3}\)?[ -]\d{3}[ -]\d{4})\b")),
    ("NAME", re.compile(r"\b(?:Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")),
]


def mask_pii(text: str) -> tuple[str, int]:
    """Redact PII. Returns (masked_text, redaction_count).

    Note: the transaction REFERENCE (REF-/BNK-/RVS-...) is intentionally NOT
    masked - it is a non-personal identifier the pipeline needs to match on.
    """
    if not text:
        return text, 0
    masked, n = text, 0
    for label, pat in _PII_PATTERNS:
        masked, k = pat.subn(f"[{label}]", masked)
        n += k
    return masked, n


# ═══════════════════════════════════════════════════════════════════════
# Control 2 - Output validation (quarantine anything that fails)
# ═══════════════════════════════════════════════════════════════════════
def validate_classification(obj: object) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, ["output is not a JSON object"]
    cat = str(obj.get("category", "")).strip().upper()
    if cat not in config.ALLOWED_CATEGORIES:
        errors.append(f"category {cat!r} not in {config.ALLOWED_CATEGORIES}")
    conf = obj.get("confidence", None)
    if conf is not None:
        try:
            conf = float(conf)
            if not 0.0 <= conf <= 1.0:
                errors.append(f"confidence {conf} out of [0,1]")
        except (TypeError, ValueError):
            errors.append("confidence not numeric")
    return (not errors), errors


def validate_extraction(obj: object) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, ["output is not a JSON object"]
    amt = obj.get("amount", None)
    if amt is not None:
        try:
            amt = float(amt)
            if not 0 < amt < config.MAX_REASONABLE_AMOUNT:
                errors.append(f"amount {amt} out of range")
        except (TypeError, ValueError):
            errors.append("amount not numeric")
    date = obj.get("date", None)
    if date:
        try:
            datetime.strptime(str(date), "%Y-%m-%d")
        except ValueError:
            errors.append(f"date {date!r} not YYYY-MM-DD")
    return (not errors), errors


# ═══════════════════════════════════════════════════════════════════════
# Control 3 - Audit log (append-only JSON lines)
# ═══════════════════════════════════════════════════════════════════════
class AuditLog:
    def __init__(self, path: Path = config.AUDIT_LOG, run_id: str | None = None):
        self.path = path
        self.run_id = run_id or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]

    def record(self, event: str, **fields) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")


# ═══════════════════════════════════════════════════════════════════════
# Control 4 - Human-in-the-loop routing (maker-checker)
# ═══════════════════════════════════════════════════════════════════════
def route(value_at_risk: float | None, confidence: float | None,
          valid: bool) -> tuple[str, str]:
    """Return (decision, reason): QUARANTINE | HUMAN | AUTO."""
    if not valid:
        return "QUARANTINE", "failed-output-validation"
    if value_at_risk is not None and value_at_risk >= config.HIGH_VALUE_THRESHOLD:
        return "HUMAN", "high-value"
    if confidence is not None and confidence < config.LOW_CONFIDENCE_THRESHOLD:
        return "HUMAN", "low-confidence"
    return "AUTO", "auto-cleared"


# ═══════════════════════════════════════════════════════════════════════
# Runner - apply all four controls over the breaks
# ═══════════════════════════════════════════════════════════════════════
def _load_inputs() -> pd.DataFrame:
    """Breaks that carry a note + their value_at_risk + the account to redact.

    Note source is notes_index.csv (written by BOTH the synthetic generator and
    the BYOD ingester), falling back to ground_truth.csv. break_type and
    value_at_risk come from the reconciled `exceptions` table, so only real
    breaks-with-notes are processed.
    """
    if config.NOTES_INDEX_CSV.exists():
        notes = pd.read_csv(config.NOTES_INDEX_CSV)[["reference", "note_text"]]
    elif config.GROUND_TRUTH_CSV.exists():
        notes = pd.read_csv(config.GROUND_TRUTH_CSV)[["reference", "note_text"]]
    else:
        return pd.DataFrame(columns=["reference", "note_text", "break_type",
                                     "value_at_risk", "account"])
    notes = notes[notes["note_text"].notna()]

    from sqlalchemy import create_engine
    try:
        exc = pd.read_sql("SELECT reference, break_type, value_at_risk FROM exceptions",
                          create_engine(config.DB_URL))
        df = notes.merge(exc, on="reference", how="inner")
    except Exception:  # noqa: BLE001 - no recon yet; process notes without value
        df = notes.assign(break_type="unknown", value_at_risk=None)

    acct = {}
    for csv in (config.LEDGER_CSV, config.BANK_FEED_CSV):
        if csv.exists():
            d = pd.read_csv(csv)
            acct.update(dict(zip(d["reference"], d["account"])))
    df["account"] = df["reference"].map(acct)
    return df.reset_index(drop=True)


def main() -> int:
    audit = AuditLog()
    live = llm.available()
    model = llm.provider_label() if live else "offline"
    df = _load_inputs()
    audit.record("run_start", model=model, n_items=len(df),
                 controls=["mask_pii", "validate", "audit", "human_in_loop"])
    print(f"[Phase 5] governance run {audit.run_id} | model={model} | items={len(df)}")

    rows, total_redactions = [], 0
    for r in df.itertuples(index=False):
        # The text we would send to the LLM = note + a line of context that
        # contains a real account number, so masking has something to redact.
        raw_input = f"{r.note_text}\nAccount on file: {r.account}"
        masked, n_red = mask_pii(raw_input)
        total_redactions += n_red

        # Classify the MASKED text. A bad/failed response is caught, not trusted.
        category, confidence, valid, errors = None, None, False, ["no-note"]
        if live:
            try:
                out = genai.classify_note(masked)
                valid, errors = validate_classification(out)
                if valid:
                    category, confidence = out["category"], out["confidence"]
            except Exception as e:  # noqa: BLE001 - treat as failed validation
                valid, errors = False, [f"exception:{type(e).__name__}"]
        else:
            from src.evaluate_prompts import offline_classify
            category = offline_classify(masked, "v2")
            confidence, valid, errors = 0.9, True, []

        decision, reason = route(getattr(r, "value_at_risk", None), confidence, valid)

        audit.record("break_processed", reference=r.reference,
                     break_type=r.break_type, pii_redactions=n_red,
                     input_sha=AuditLog._hash(masked), llm_category=category,
                     confidence=confidence, valid=valid, errors=errors,
                     value_at_risk=getattr(r, "value_at_risk", None),
                     decision=decision, reason=reason)

        rows.append({
            "reference": r.reference, "break_type": r.break_type,
            "value_at_risk": getattr(r, "value_at_risk", None),
            "llm_category": category, "confidence": confidence,
            "valid": valid, "errors": "; ".join(errors) if errors else "",
            "decision": decision, "reason": reason,
            "masked_input": masked.replace("\n", " | "),
        })

    out = pd.DataFrame(rows)
    (config.REPORTS_DIR / "governed_exceptions.csv").write_text(
        out.to_csv(index=False), encoding="utf-8")
    out[out.decision == "QUARANTINE"].to_csv(
        config.REPORTS_DIR / "quarantine.csv", index=False)
    out[out.decision == "HUMAN"].to_csv(
        config.REPORTS_DIR / "approvals_queue.csv", index=False)

    counts = out["decision"].value_counts().to_dict()
    audit.record("run_end", decisions=counts, total_pii_redactions=total_redactions)

    print(f"[Phase 5] PII redactions applied : {total_redactions}")
    print(f"[Phase 5] decisions              : {counts}")
    print(f"[Phase 5] audit log              : {config.AUDIT_LOG.name} "
          f"(+{len(df)+2} records this run)")
    print(f"[Phase 5] outputs                : governed_exceptions.csv, "
          f"quarantine.csv, approvals_queue.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
