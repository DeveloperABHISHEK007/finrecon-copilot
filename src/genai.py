"""
Phase 4 - The GenAI layer (the star of the show).

For each break, the LLM reads the messy remittance note and does three things
the JD names directly, each returning STRICT, VALIDATED JSON:

    classify_note(note)   -> TIMING | DUPLICATE | DATA_ERROR | MISSING (+confidence)
    extract_fields(note)  -> {reference, amount, date}
    summarise_day(rows)   -> short manager-friendly narrative (plain text)

Rules that matter (say these in the interview):
    - temperature 0 (config.LLM_TEMPERATURE) for repeatability
    - the LLM ONLY reads language - it NEVER does the reconciliation math
    - every JSON response is parsed and validated (pydantic) before use;
      invalid output is rejected, not trusted

Provider is chosen in .env (LLM_PROVIDER=groq). See src/llm.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import llm  # noqa: E402

CompleteFn = Callable[[str], str]

# ── Validation schemas ─────────────────────────────────────────────────
class Classification(BaseModel):
    category: str
    confidence: float = 0.5
    rationale: str = ""

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str) -> str:
        v = str(v).strip().upper()
        if v not in config.ALLOWED_CATEGORIES:
            raise ValueError(f"category {v!r} not in {config.ALLOWED_CATEGORIES}")
        return v

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class Extraction(BaseModel):
    reference: str | None = None
    amount: float | None = None
    date: str | None = None


# ── Prompts ────────────────────────────────────────────────────────────
CLASSIFY_SYSTEM = (
    "You are a finance reconciliation assistant. You read a short, messy human "
    "remittance note about a reconciliation break and classify its cause. "
    "You never do arithmetic; you only interpret the language. "
    "Respond with a single JSON object and nothing else."
)

_CATEGORY_DEFS = (
    "TIMING     - a genuine transaction that posts on a different day (e.g. "
    "'paid next day', 'settles T+1', 'value date difference').\n"
    "DUPLICATE  - the same transaction booked more than once, or a reversal/retry "
    "(e.g. 'entered twice', 'double booked', 'reversal', 're-sent').\n"
    "DATA_ERROR - a data-entry mistake, usually the wrong amount (e.g. 'keyed "
    "wrong', 'typo', 'fat-finger', '9,000 vs 90,000').\n"
    "MISSING    - a real entry present on one side but never booked on the other "
    "(e.g. 'not booked in ledger', 'bank fee never booked', 'needs posting')."
)


def _classify_prompt(note: str, version: str) -> str:
    if version == "v1":
        # Basic first attempt - deliberately minimal (baseline for the eval).
        return (
            "Classify this reconciliation note as one of TIMING, DUPLICATE, "
            "DATA_ERROR, MISSING.\n"
            f'Note: "{note}"\n'
            'Return JSON: {"category": "..."}'
        )
    # v2 - improved: definitions, strict output contract, confidence + rationale.
    return (
        "Classify the reconciliation break described in the NOTE into exactly one "
        "category. Use these definitions:\n"
        f"{_CATEGORY_DEFS}\n\n"
        f'NOTE: "{note}"\n\n'
        "Return ONLY this JSON object:\n"
        '{"category": "<TIMING|DUPLICATE|DATA_ERROR|MISSING>", '
        '"confidence": <0.0-1.0>, "rationale": "<max 12 words>"}'
    )


_EXTRACT_PROMPT = (
    "Extract the structured fields from this remittance note. If a field is not "
    "present, use null. Do not calculate anything.\n"
    'NOTE: "{note}"\n\n'
    "Return ONLY this JSON:\n"
    '{{"reference": "<id or null>", "amount": <number or null>, '
    '"date": "<YYYY-MM-DD or null>"}}'
)


# ── JSON helpers ───────────────────────────────────────────────────────
def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response (handles code fences)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise ValueError(f"No JSON object found in model output: {text[:120]!r}")
        return json.loads(m.group(0))


def _default_complete(system: str) -> CompleteFn:
    return lambda p: llm.complete(p, system=system, json_mode=True)


# ── The three tasks ────────────────────────────────────────────────────
def classify_note(note: str, version: str = "v2",
                  complete_fn: CompleteFn | None = None) -> dict:
    """Classify a break note -> validated {category, confidence, rationale}."""
    fn = complete_fn or _default_complete(CLASSIFY_SYSTEM)
    raw = fn(_classify_prompt(note, version))
    return Classification(**_extract_json(raw)).model_dump()


def extract_fields(note: str, complete_fn: CompleteFn | None = None) -> dict:
    """Extract reference/amount/date -> validated JSON (information extraction)."""
    fn = complete_fn or _default_complete(
        "You extract structured fields from finance notes. Return JSON only.")
    raw = fn(_EXTRACT_PROMPT.format(note=note))
    return Extraction(**_extract_json(raw)).model_dump()


def summarise_day(breaks: list[dict], complete_fn: CompleteFn | None = None) -> str:
    """Summarise the day's exceptions into a short manager-friendly narrative.

    The numbers are computed HERE in code (rules for the math); the LLM only
    phrases the pre-computed facts (AI for the language) and must not alter them.
    """
    from collections import Counter

    def _var(b: dict) -> float:
        try:
            return float(b.get("value_at_risk") or 0)
        except (TypeError, ValueError):
            return 0.0

    n = len(breaks)
    by_type = Counter(b.get("break_type") for b in breaks)
    top_type, top_n = by_type.most_common(1)[0] if by_type else ("none", 0)
    total_var = sum(_var(b) for b in breaks)
    largest = max(breaks, key=_var, default=None)

    facts = (
        f"total_breaks = {n}\n"
        f"breaks_by_cause = {dict(by_type)}\n"
        f"most_common_cause = {top_type} ({top_n})\n"
        f"total_value_at_risk = {total_var:,.2f}\n"
        + (f"largest_exposure = {largest.get('reference')} "
           f"({_var(largest):,.2f})" if largest else "largest_exposure = n/a")
    )
    prompt = (
        "Write a concise 3-4 sentence end-of-day reconciliation summary for a "
        "finance manager using ONLY these pre-computed facts. Do NOT add, change "
        "or recompute any numbers.\n\nFACTS:\n" + facts
    )
    fn = complete_fn or (lambda p: llm.complete(
        p, system="You write concise, factual finance summaries.", json_mode=False))
    return fn(prompt).strip()


# ── Self-test (runs without an API key) ────────────────────────────────
def _selftest() -> None:
    """Prove the parser + validator work on a canned response (no network)."""
    canned = '```json\n{"category":"data_error","confidence":1.2,'\
             '"rationale":"wrong amount keyed"}\n```'
    out = classify_note("amount keyed wrong", complete_fn=lambda _p: canned)
    assert out["category"] == "DATA_ERROR" and out["confidence"] == 1.0, out
    ex = extract_fields("x", complete_fn=lambda _p: '{"reference":"REF-1",'
                        '"amount":"1234.5","date":"2026-01-02"}')
    assert ex["reference"] == "REF-1" and ex["amount"] == 1234.5, ex
    print("genai self-test: JSON parsing + validation OK")


if __name__ == "__main__":
    print("provider:", llm.provider_label(), "| available:", llm.available())
    _selftest()
    if llm.available():
        demo = "ref REF-000113 amount keyed wrong, should be 151,881.14 not shown, typo, 2026-06-20"
        print("live classify:", classify_note(demo))
        print("live extract :", extract_fields(demo))
    else:
        print("(no API key set - add GROQ_API_KEY to .env to run live calls)")
