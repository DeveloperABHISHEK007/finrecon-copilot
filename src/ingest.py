"""
Bring-your-own-data ingester - turn YOUR messy CSVs into the canonical schema.

Drop two CSV files in data/input/:
    ledger_raw.csv   - your general ledger export
    bank_raw.csv     - your bank / settlement feed export
(names configurable in config.py). Then run:

    python -m src.ingest

It figures out which of your columns map to reference / txn_date / amount /
account / currency (auto-detection with lots of aliases), cleans the messy
values (strips $ , spaces, currency symbols, parses many date formats, upper-
cases references), pulls any free-text note/memo column into notes_index.csv
for the LLM to read, and writes the canonical files the pipeline expects:

    data/ledger.csv
    data/bank_feed.csv
    data/notes_index.csv     (reference -> note_text, if a note column exists)

After ingest, run Phases 2-5 (e.g. `python run.py --input`). There is no
ground-truth for your own data, so accuracy scoring is skipped - everything
else (reconciliation, LLM classification, governance, dashboard) works.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

# Canonical field -> candidate source column names (normalised: lower, alnum only).
ALIASES: dict[str, list[str]] = {
    "reference": ["reference", "ref", "refno", "id", "transactionid", "txnid",
                  "txnref", "txnreference", "transactionref", "docno", "documentno",
                  "paymentref", "invoiceno", "invoice", "transactionreference"],
    "txn_date": ["txndate", "date", "valuedate", "postingdate", "transactiondate",
                 "bookingdate", "paymentdate", "settlementdate", "effectivedate"],
    "amount": ["amount", "amt", "value", "transactionamount", "paymentamount",
               "paidamount", "grossamount", "netamount"],
    "account": ["account", "acct", "accountno", "accountnumber", "acctno", "iban",
                "glaccount", "bankaccount"],
    "currency": ["currency", "ccy", "curr", "currencycode"],
    "note": ["note", "notes", "memo", "description", "remittance", "remittancenote",
             "narrative", "details", "remarks", "comment", "comments", "reason"],
}
CURRENCY_SYMBOLS = "$£€₹¥"


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def detect_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map canonical field -> actual column name in df (best match)."""
    norm_to_actual = {_norm(c): c for c in df.columns}
    mapping: dict[str, str] = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if alias in norm_to_actual:
                mapping[field] = norm_to_actual[alias]
                break
    return mapping


def clean_amount(series: pd.Series) -> pd.Series:
    """'$1,250.00', ' (500) ', '1 234,56'-ish -> float."""
    def one(v):
        if pd.isna(v):
            return None
        s = str(v).strip()
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        for sym in CURRENCY_SYMBOLS:
            s = s.replace(sym, "")
        s = s.replace(" ", "").replace(",", "")
        try:
            val = float(s)
        except ValueError:
            return None
        return -val if neg else val
    return series.map(one)


def clean_frame(df: pd.DataFrame, name: str) -> tuple[pd.DataFrame, str | None]:
    """Return (canonical_df, note_column_or_None)."""
    m = detect_columns(df)
    missing = [f for f in ("reference", "amount") if f not in m]
    if missing:
        raise ValueError(
            f"{name}: could not find column(s) for {missing}. "
            f"Detected: {m}. Columns present: {list(df.columns)}. "
            f"Rename your column or add an alias in src/ingest.py ALIASES.")

    out = pd.DataFrame()
    out["reference"] = df[m["reference"]].astype(str).str.strip().str.upper()
    out["txn_date"] = (pd.to_datetime(df[m["txn_date"]], errors="coerce").dt.date
                       if "txn_date" in m else pd.NaT)
    out["amount"] = clean_amount(df[m["amount"]])
    out["account"] = (df[m["account"]].astype(str).str.strip()
                      if "account" in m else "")
    out["currency"] = (df[m["currency"]].astype(str).str.strip().str.upper()
                       if "currency" in m else "USD")

    before = len(out)
    out = out.dropna(subset=["reference", "amount"])
    dropped = before - len(out)

    print(f"[ingest] {name}: mapped {m}")
    if dropped:
        print(f"[ingest] {name}: dropped {dropped} row(s) with no reference/amount")
    return out, m.get("note")


def main() -> int:
    if not config.INPUT_LEDGER_CSV.exists() or not config.INPUT_BANK_CSV.exists():
        print("[ingest] Put your files here first:")
        print(f"           {config.INPUT_LEDGER_CSV}")
        print(f"           {config.INPUT_BANK_CSV}")
        print("[ingest] (see data/input/*.example.csv for the idea, and "
              "docs/bring_your_own_data.md)")
        return 1

    raw_led = pd.read_csv(config.INPUT_LEDGER_CSV, dtype=str)
    raw_bank = pd.read_csv(config.INPUT_BANK_CSV, dtype=str)

    ledger, led_note = clean_frame(raw_led, "ledger")
    bank, bank_note = clean_frame(raw_bank, "bank_feed")

    ledger.to_csv(config.LEDGER_CSV, index=False)
    bank.to_csv(config.BANK_FEED_CSV, index=False)

    # Pull notes (reference -> note_text) from whichever side has a note column.
    notes = {}
    for raw, note_col in ((raw_led, led_note), (raw_bank, bank_note)):
        if note_col:
            ref_col = detect_columns(raw)["reference"]
            for ref, txt in zip(raw[ref_col], raw[note_col]):
                if pd.notna(txt) and str(txt).strip():
                    notes[str(ref).strip().upper()] = str(txt).strip()
    if notes:
        pd.DataFrame({"reference": list(notes), "note_text": list(notes.values())}
                     ).to_csv(config.NOTES_INDEX_CSV, index=False)

    # There is no ground truth for provided data - remove any stale synthetic one
    # so downstream validation is correctly skipped.
    if config.GROUND_TRUTH_CSV.exists():
        config.GROUND_TRUTH_CSV.unlink()

    print(f"[ingest] wrote {len(ledger)} ledger + {len(bank)} bank rows "
          f"-> {config.LEDGER_CSV.name}, {config.BANK_FEED_CSV.name}")
    print(f"[ingest] notes extracted: {len(notes)} -> "
          f"{config.NOTES_INDEX_CSV.name if notes else '(none - no note column found)'}")
    print("[ingest] next: python run.py --input")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
