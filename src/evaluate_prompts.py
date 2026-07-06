"""
Phase 4 (companion) - Prompt evaluation harness.

Runs the classifier over the labelled remittance notes (from ground_truth.csv),
computes accuracy, shows a confusion breakdown and the failures, and compares
prompt version v1 vs v2 - i.e. the JD's "prompt testing, evaluation, optimization",
measured rather than guessed.

Modes:
    LIVE     - if an API key is set, calls the real LLM (src/genai.classify_note).
    OFFLINE  - no key: uses a transparent keyword heuristic (v1 weak, v2 strong)
               so the harness is fully runnable now; clearly labelled as offline.

Run:   python -m src.evaluate_prompts
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import genai, llm  # noqa: E402

# Offline keyword heuristics. v2 knows more synonyms than v1 -> higher accuracy,
# which demonstrates "improving the prompt and re-running".
_KEYWORDS = {
    "v1": {
        "DUPLICATE": ["twice", "duplicate", "double"],
        "DATA_ERROR": ["typo", "wrong"],
        "TIMING": ["timing", "next day"],
        "MISSING": ["not booked", "missing"],
    },
    "v2": {
        "DUPLICATE": ["twice", "duplicate", "dup", "double", "reversal", "retry",
                      "re-sent", "resent", "net zero", "2x", "dedupe"],
        "DATA_ERROR": ["typo", "wrong", "keyed wrong", "fat-finger", "fat finger",
                       "wrong amt", "wrong amount", "data entry", " vs ", "captured"],
        "TIMING": ["timing", "next day", "next biz", "t+1", "value date", "lag",
                   "settles", "settle", "clear", "following day"],
        "MISSING": ["not booked", "never booked", "missing", "no matching",
                    "needs posting", "bank fee", "gl missing"],
    },
}


def offline_classify(note: str, version: str) -> str:
    text = note.lower()
    scores = {cat: sum(text.count(k) for k in kws)
              for cat, kws in _KEYWORDS[version].items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "TIMING"  # fallback guess if no keyword


def load_labelled() -> pd.DataFrame:
    gt = pd.read_csv(config.GROUND_TRUTH_CSV)
    df = gt[gt["note_file"].notna()][["note_text", "expected_category"]].copy()
    df = df.dropna(subset=["note_text"]).reset_index(drop=True)
    return df


def run_version(df: pd.DataFrame, version: str, live: bool) -> dict:
    preds, errors = [], 0
    for note in df["note_text"]:
        try:
            if live:
                preds.append(genai.classify_note(note, version=version)["category"])
            else:
                preds.append(offline_classify(note, version))
        except Exception as e:  # noqa: BLE001 - a bad response counts as a miss
            errors += 1
            preds.append(f"ERROR:{type(e).__name__}")
    df = df.assign(pred=preds)
    correct = int((df["pred"] == df["expected_category"]).sum())
    acc = 100.0 * correct / len(df)
    confusion = Counter(zip(df["expected_category"], df["pred"]))
    failures = df[df["pred"] != df["expected_category"]]
    return {"version": version, "accuracy": acc, "correct": correct,
            "n": len(df), "errors": errors, "confusion": confusion,
            "failures": failures}


def main() -> int:
    df = load_labelled()
    live = llm.available()
    mode = f"LIVE ({llm.provider_label()})" if live else "OFFLINE heuristic (no API key)"
    print(f"=== Prompt evaluation harness ===")
    print(f"mode           : {mode}")
    print(f"labelled notes : {len(df)}\n")

    results = {v: run_version(df, v, live) for v in ("v1", "v2")}

    print(f"{'version':<10}{'accuracy':>12}{'correct':>10}{'errors':>9}")
    for v in ("v1", "v2"):
        r = results[v]
        print(f"{v:<10}{r['accuracy']:>11.1f}%{r['correct']:>10}{r['errors']:>9}")
    delta = results["v2"]["accuracy"] - results["v1"]["accuracy"]
    print(f"\nimprovement v1 -> v2: {delta:+.1f} percentage points")

    # Show where v2 still gets it wrong (the input to the next optimization round).
    fails = results["v2"]["failures"]
    print(f"\nv2 misclassifications ({len(fails)}):")
    if len(fails) == 0:
        print("  (none)")
    for _, row in fails.head(10).iterrows():
        note = row["note_text"][:70].replace("\n", " ")
        print(f"  expected={row['expected_category']:<11} got={row['pred']:<11} | {note}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
