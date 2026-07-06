# Bring your own data — run FinRecon on your real CSVs

The project ships with a synthetic-data generator, but you can point it at your
own messy exports instead. The ingester auto-detects your columns, cleans the
values, and pulls the free-text notes out for the LLM to read.

---

## 1. Put your two files here

```
data/input/ledger_raw.csv     your general ledger export
data/input/bank_raw.csv       your bank / settlement feed export
```

There are worked examples next to them — **`data/input/ledger_raw.example.csv`**
and **`bank_raw.example.csv`** — showing the kind of mess the ingester handles
(`$`, thousands commas, spaces, mixed date formats, lower-case refs, a memo
column). To try them:

```bash
cp data/input/ledger_raw.example.csv data/input/ledger_raw.csv
cp data/input/bank_raw.example.csv   data/input/bank_raw.csv
```

Your real files stay local — `data/input/*.csv` is git-ignored (only the
`*.example.csv` templates are tracked).

---

## 2. What columns are needed

The ingester maps YOUR column names to the canonical fields automatically. It
recognises lots of aliases (case/spacing/punctuation-insensitive):

| Canonical field | Required? | Example header names it recognises |
|---|---|---|
| **reference** | yes | Reference, Ref, Txn Ref, Transaction ID, Invoice No, Doc No |
| **amount** | yes | Amount, Amt, Value, Paid Amount, Payment Amount |
| txn_date | no | Date, Value Date, Posting Date, Transaction Date |
| account | no | Account, Acct, Account No, IBAN, GL Account |
| currency | no | Currency, Ccy, Curr |
| **note / memo** | no (but needed for the AI step) | Note, Memo, Description, Remittance Note, Narrative, Remarks |

- Only **reference** and **amount** are mandatory. Missing `currency` defaults to
  USD; missing `txn_date` just disables the trend chart.
- The **note/memo column is what the LLM reads.** Put your free-text break
  explanations there (usually on the bank feed). No note column → reconciliation
  still runs, but breaks are routed to a human as `NEEDS_REVIEW` (nothing for the
  AI to classify).
- Don't have a matching alias? Add yours to `ALIASES` in `src/ingest.py` (one line).

**The messy values it cleans for you:** `$`, `£`, `€`, `₹` symbols; thousands
commas; surrounding spaces; `(500)` negatives; many date formats; lower-case and
mixed-case references (upper-cased so they match).

---

## 3. Run it

```bash
python -m src.ingest        # normalise your files -> data/ledger.csv, bank_feed.csv, notes_index.csv
python run.py --input       # reconcile + AI + governance + dashboard on YOUR data
```

`--input` tells `run.py` to ingest your files instead of generating synthetic
data. Because your data has no answer key, accuracy scoring is **skipped**;
everything else runs: SQL/pandas reconciliation, the LLM reading your notes,
PII masking + validation + audit + human-in-the-loop, and the dashboard.

Review the results exactly as before:
- `reports/dashboard.html` — the visual dashboard
- `reports/exceptions_report.xlsx` — the breaks workbook
- `reports/approvals_queue.csv` — what needs human sign-off
- `reports/audit.log` — the audit trail

---

## 4. Notes & limits

- **Duplicates** are detected by a reference appearing more than once on the bank
  side — keep your real duplicate rows in; the pipeline flags them (it does not
  silently drop them).
- **Reversals** are auto-excluded when a reference's rows net to ~0 across 2+
  entries. If your reversals look different, adjust the rule in
  `sql/reconciliation.sql` / `src/reconcile.py`.
- **Debit/Credit columns:** if your amount is split across separate debit and
  credit columns, combine them into one signed `amount` column before ingest
  (or extend `clean_frame` in `src/ingest.py`).
- **Matching key:** reconciliation matches on `reference`. Both files must share
  the same reference values for rows that should reconcile.
- To go back to the synthetic showcase: `python -m src.generate_data` then
  `python run.py`.
