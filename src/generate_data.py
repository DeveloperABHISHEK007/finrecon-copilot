"""
Phase 1 - Synthetic data generator.

Builds two datasets that SHOULD reconcile (a general ledger and a bank feed),
deliberately injects realistic breaks, and writes messy free-text remittance
notes (some as PDF) for the LLM to read later.

Why synthetic: zero data-privacy risk, and we control the breaks - so we can
score the pipeline against a ground-truth file.

Outputs (see config.py):
    data/ledger.csv        the "clean" general ledger
    data/bank_feed.csv     the bank feed, with breaks injected
    data/ground_truth.csv  every seeded break + expected LLM category + note file
    data/notes/*.txt|*.pdf  messy human remittance notes

Break types seeded:
    missing-in-bank, missing-in-ledger, amount-mismatch, duplicate, reversal

Run:   python src/generate_data.py            (or  python -m src.generate_data)
Deterministic: fixed seeds -> identical data every run (safe to re-run).
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pandas as pd
from faker import Faker
from fpdf import FPDF
from fpdf.enums import XPos, YPos

# Make the project root importable so `import config` works when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

# ----------------------------------------------------------------------
# Tunables - change these to make the dataset bigger / breakier.
# ----------------------------------------------------------------------
SEED = 42
N_LEDGER = 1000

N_MISSING_IN_BANK = 20     # in ledger, dropped from bank feed
N_MISSING_IN_LEDGER = 15   # only in bank feed (new references)
N_AMOUNT_MISMATCH = 25     # same reference, wrong amount (data-entry typo)
N_DUPLICATE = 12           # booked twice in the bank feed
N_REVERSAL = 10            # a +/- reversal (retry) pair in the bank feed

CURRENCIES = ["USD", "USD", "USD", "EUR", "GBP", "INR"]  # weighted toward USD

# How many of each break get a human note (the LLM's unstructured input).
# We also choose which get a PDF vs a .txt file.
NOTES_PER_TYPE = {
    "amount-mismatch": 8,
    "duplicate": 6,
    "missing-in-bank": 8,
    "missing-in-ledger": 6,
    "reversal": 5,
}
PDF_EVERY = 3  # every 3rd note is written as a PDF instead of .txt

# Break type -> the category the LLM should predict (Phase 4 ground truth).
BREAK_TO_CATEGORY = {
    "amount-mismatch": "DATA_ERROR",
    "duplicate": "DUPLICATE",
    "missing-in-bank": "TIMING",     # assume timing: will post next day
    "missing-in-ledger": "MISSING",  # bank has it, ledger never booked it
    "reversal": "DUPLICATE",         # a retry that was reversed
}

# Messy, human note templates per category. {ref}/{amt}/{date} are filled in
# with deliberately varied formatting to make extraction non-trivial.
NOTE_TEMPLATES = {
    "TIMING": [
        "ref {ref} - pmt {amt} {cur} went out {date}, bank posts next biz day, will clear T+1",
        "{ref}: value date diff, paid {date} but settles following day. amt {amt}. not a real break",
        "hey - {ref} for {amt} is just timing, hit our side {date}, bank feed lags a day",
    ],
    "DUPLICATE": [
        "{ref} entered twice by mistake, double booked {amt} {cur} on {date}. please dedupe",
        "dup!! ref {ref} appears 2x in the feed, only one {amt} charge is real ({date})",
        "reversal/retry on {ref} - first attempt failed then re-sent, net zero, {amt} {date}",
    ],
    "DATA_ERROR": [
        "amount keyed wrong on {ref} - should be {amt} {cur} not what's showing, typo, dated {date}",
        "{ref} fat-finger: entered 9,000 vs 90,000 kind of error. correct is {amt}. {date}",
        "data entry error {ref}, wrong amt captured, right value {amt} {cur} on {date}",
    ],
    "MISSING": [
        "{ref} not booked in ledger yet - bank shows {amt} {cur} on {date}, GL missing it",
        "bank fee {amt} on {date} ({ref}) never booked our side, needs posting",
        "missing entry: {ref} for {amt} {cur} present in bank {date}, no matching GL line",
    ],
}


def _money(rng: random.Random) -> float:
    """A realistic invoice-ish amount, 2dp."""
    band = rng.choice([1, 1, 1, 2, 2, 3])  # skew toward smaller values
    if band == 1:
        val = rng.uniform(50, 5_000)
    elif band == 2:
        val = rng.uniform(5_000, 50_000)
    else:
        val = rng.uniform(50_000, 250_000)
    return round(val, 2)


def _typo_amount(amount: float, rng: random.Random) -> float:
    """Introduce a realistic data-entry error (dropped/added zero or transpose)."""
    kind = rng.choice(["drop_zero", "add_zero", "transpose"])
    if kind == "drop_zero":
        return round(amount / 10, 2)
    if kind == "add_zero":
        return round(amount * 10, 2)
    # transpose two digits of the integer part
    s = list(str(int(amount)))
    if len(s) >= 2:
        i = rng.randrange(len(s) - 1)
        s[i], s[i + 1] = s[i + 1], s[i]
    frac = round(amount - int(amount), 2)
    return round(float("".join(s)) + frac, 2)


def generate_ledger(fake: Faker, rng: random.Random) -> pd.DataFrame:
    rows = []
    for i in range(1, N_LEDGER + 1):
        rows.append({
            "reference": f"REF-{i:06d}",
            "txn_date": fake.date_between(start_date="-90d", end_date="today").isoformat(),
            "amount": _money(rng),
            "account": f"AC-{rng.randrange(10_000_000, 99_999_999)}",
            "currency": rng.choice(CURRENCIES),
        })
    return pd.DataFrame(rows)


def inject_breaks(ledger: pd.DataFrame, fake: Faker, rng: random.Random):
    """Return (bank_feed_df, list_of_ground_truth_dicts)."""
    # Start the bank feed as a faithful copy of the ledger.
    bank = ledger.copy(deep=True)
    truth: list[dict] = []

    # Pick disjoint sets of ledger references for each break type.
    all_refs = ledger["reference"].tolist()
    rng.shuffle(all_refs)
    cursor = 0

    def take(n: int) -> list[str]:
        nonlocal cursor
        chunk = all_refs[cursor:cursor + n]
        cursor += n
        return chunk

    mismatch_refs = take(N_AMOUNT_MISMATCH)
    missing_bank_refs = take(N_MISSING_IN_BANK)
    dup_refs = take(N_DUPLICATE)

    led_idx = ledger.set_index("reference")

    # 1) amount-mismatch: change the amount on the bank side.
    for ref in mismatch_refs:
        orig = float(led_idx.loc[ref, "amount"])
        wrong = _typo_amount(orig, rng)
        # A transpose can swap two equal digits -> no change. Guarantee a real diff.
        while abs(wrong - orig) < config.AMOUNT_TOLERANCE:
            wrong = _typo_amount(orig, rng)
        bank.loc[bank["reference"] == ref, "amount"] = wrong
        truth.append({
            "reference": ref, "break_type": "amount-mismatch",
            "expected_category": BREAK_TO_CATEGORY["amount-mismatch"],
            "ledger_amount": orig, "bank_amount": wrong,
            "currency": led_idx.loc[ref, "currency"],
            "txn_date": led_idx.loc[ref, "txn_date"],
        })

    # 2) missing-in-bank: drop these rows from the bank feed.
    bank = bank[~bank["reference"].isin(missing_bank_refs)].copy()
    for ref in missing_bank_refs:
        truth.append({
            "reference": ref, "break_type": "missing-in-bank",
            "expected_category": BREAK_TO_CATEGORY["missing-in-bank"],
            "ledger_amount": float(led_idx.loc[ref, "amount"]), "bank_amount": None,
            "currency": led_idx.loc[ref, "currency"],
            "txn_date": led_idx.loc[ref, "txn_date"],
        })

    # 3) duplicate: append a second identical bank row.
    dup_rows = bank[bank["reference"].isin(dup_refs)].copy()
    bank = pd.concat([bank, dup_rows], ignore_index=True)
    for ref in dup_refs:
        truth.append({
            "reference": ref, "break_type": "duplicate",
            "expected_category": BREAK_TO_CATEGORY["duplicate"],
            "ledger_amount": float(led_idx.loc[ref, "amount"]),
            "bank_amount": float(led_idx.loc[ref, "amount"]),
            "currency": led_idx.loc[ref, "currency"],
            "txn_date": led_idx.loc[ref, "txn_date"],
        })

    # 4) reversal / retry: a self-cancelling +/- pair that lives ONLY in the
    #    bank feed (nets to zero). Recon must detect and EXCLUDE these before
    #    aggregating - they are not breaks and must not count as missing-in-ledger.
    rev_rows = []
    for i in range(N_REVERSAL):
        ref = f"RVS-{i + 1:06d}"
        amt = _money(rng)
        date = fake.date_between(start_date="-90d", end_date="today").isoformat()
        cur = rng.choice(CURRENCIES)
        acc = f"AC-{rng.randrange(10_000_000, 99_999_999)}"
        rev_rows.append({"reference": ref, "txn_date": date, "amount": amt,
                         "account": acc, "currency": cur})
        rev_rows.append({"reference": ref, "txn_date": date, "amount": round(-amt, 2),
                         "account": acc, "currency": cur})
        truth.append({
            "reference": ref, "break_type": "reversal",
            "expected_category": BREAK_TO_CATEGORY["reversal"],
            "ledger_amount": None, "bank_amount": amt,
            "currency": cur, "txn_date": date,
        })
    if rev_rows:
        bank = pd.concat([bank, pd.DataFrame(rev_rows)], ignore_index=True)

    # 5) missing-in-ledger: brand-new references only in the bank feed.
    new_rows = []
    for i in range(N_MISSING_IN_LEDGER):
        ref = f"BNK-{i + 1:06d}"
        amt = _money(rng)
        date = fake.date_between(start_date="-90d", end_date="today").isoformat()
        cur = rng.choice(CURRENCIES)
        new_rows.append({
            "reference": ref, "txn_date": date, "amount": amt,
            "account": f"AC-{rng.randrange(10_000_000, 99_999_999)}", "currency": cur,
        })
        truth.append({
            "reference": ref, "break_type": "missing-in-ledger",
            "expected_category": BREAK_TO_CATEGORY["missing-in-ledger"],
            "ledger_amount": None, "bank_amount": amt,
            "currency": cur, "txn_date": date,
        })
    if new_rows:
        bank = pd.concat([bank, pd.DataFrame(new_rows)], ignore_index=True)

    # Shuffle so breaks aren't all at the bottom (realism).
    bank = bank.sample(frac=1.0, random_state=SEED).reset_index(drop=True)
    return bank, truth


def _write_pdf_note(path: Path, text: str) -> None:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 10, "Remittance Note", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(2)
    pdf.multi_cell(0, 7, text.encode("latin-1", "replace").decode("latin-1"))
    pdf.output(str(path))


def generate_notes(truth: list[dict], rng: random.Random) -> None:
    """Write messy notes for a subset of breaks; record the file on each truth row."""
    config.NOTES_DIR.mkdir(parents=True, exist_ok=True)
    # Clear any notes from a previous run so re-runs are clean/idempotent.
    for old in config.NOTES_DIR.glob("note_*.*"):
        old.unlink()

    by_type: dict[str, list[dict]] = {}
    for row in truth:
        by_type.setdefault(row["break_type"], []).append(row)

    note_seq = 0
    for btype, want in NOTES_PER_TYPE.items():
        rows = by_type.get(btype, [])
        rng.shuffle(rows)
        for row in rows[:want]:
            note_seq += 1
            category = BREAK_TO_CATEGORY[btype]
            template = rng.choice(NOTE_TEMPLATES[category])
            amt = row["bank_amount"] if row["bank_amount"] is not None else row["ledger_amount"]
            text = template.format(
                ref=row["reference"],
                amt=f"{amt:,.2f}" if amt is not None else "?",
                cur=row["currency"],
                date=row["txn_date"],
            )
            is_pdf = (note_seq % PDF_EVERY == 0)
            ext = "pdf" if is_pdf else "txt"
            fname = f"note_{note_seq:03d}_{row['reference']}.{ext}"
            fpath = config.NOTES_DIR / fname
            if is_pdf:
                _write_pdf_note(fpath, text)
            else:
                fpath.write_text(text, encoding="utf-8")
            row["note_file"] = f"notes/{fname}"
            row["note_text"] = text


def main() -> None:
    fake = Faker()
    Faker.seed(SEED)
    rng = random.Random(SEED)

    print(f"[Phase 1] Generating {N_LEDGER} ledger rows (seed={SEED}) ...")
    ledger = generate_ledger(fake, rng)

    print("[Phase 1] Injecting breaks into the bank feed ...")
    bank, truth = inject_breaks(ledger, fake, rng)

    print("[Phase 1] Writing messy remittance notes (txt + pdf) ...")
    generate_notes(truth, rng)

    # Persist everything.
    ledger.to_csv(config.LEDGER_CSV, index=False)
    bank.to_csv(config.BANK_FEED_CSV, index=False)
    truth_df = pd.DataFrame(truth)
    # stable, readable column order
    cols = ["reference", "break_type", "expected_category", "ledger_amount",
            "bank_amount", "currency", "txn_date", "note_file", "note_text"]
    for c in cols:
        if c not in truth_df.columns:
            truth_df[c] = None
    truth_df = truth_df[cols].sort_values(["break_type", "reference"]).reset_index(drop=True)
    truth_df.to_csv(config.GROUND_TRUTH_CSV, index=False)

    # Summary (great to screenshot for the write-up).
    n_notes = len(list(config.NOTES_DIR.glob("note_*.*")))
    n_pdf = len(list(config.NOTES_DIR.glob("note_*.pdf")))
    print("\n[Phase 1] Done. Summary")
    print(f"  ledger.csv        : {len(ledger):>5} rows -> {config.LEDGER_CSV.name}")
    print(f"  bank_feed.csv     : {len(bank):>5} rows -> {config.BANK_FEED_CSV.name}")
    print(f"  ground_truth.csv  : {len(truth_df):>5} seeded breaks")
    print(f"  notes/            : {n_notes:>5} notes ({n_pdf} pdf, {n_notes - n_pdf} txt)")
    print("  breaks by type    :")
    for btype, n in truth_df["break_type"].value_counts().sort_index().items():
        print(f"      {btype:<18}: {n}")


if __name__ == "__main__":
    main()
