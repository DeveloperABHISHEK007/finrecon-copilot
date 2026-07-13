# Phase 7 — Power BI dashboard: step-by-step build guide

The manager-facing frontend. Power BI Desktop is a GUI tool, so this is a
build guide you follow once; it produces `powerbi/FinRecon.pbix`.

> Time: ~30–45 min. Free tool: **Power BI Desktop** (Windows) —
> https://www.microsoft.com/power-platform/products/power-bi/desktop/

---

## Step 0 — Produce the data

```bash
python run.py                 # runs the pipeline (creates the DB + reports)
python -m src.export_powerbi  # writes powerbi/finrecon_powerbi.csv
```

`finrecon_powerbi.csv` is one tidy fact table (1 row per reference):

| column | meaning |
|---|---|
| reference | transaction id |
| break_type | matched / amount-mismatch / missing-in-bank / missing-in-ledger / duplicate |
| is_break | 1 if a break, 0 if matched (drives Match Rate) |
| ledger_amount, bank_amount, amount_diff | the money |
| value_at_risk | exposure of this break |
| currency, txn_date, month, age_days | dimensions for slicing / trend / aging |
| llm_category, confidence | what the LLM inferred (for breaks with a note) |
| decision, reason | AUTO / HUMAN / NEEDS_REVIEW / MATCHED (maker-checker) |

---

## Step 1 — Import into Power BI Desktop

1. **Home → Get data → Text/CSV** → pick `powerbi/finrecon_powerbi.csv` → **Load**.
2. In **Model/Table view**, confirm column types:
   - `txn_date` → Date; `value_at_risk`, `ledger_amount`, `bank_amount`,
     `amount_diff`, `confidence` → Decimal number; `is_break`, `age_days` → Whole number.

*(Alternative source: connect to `data/finrecon.db` via an SQLite ODBC driver, or
import `reports/exceptions_report.xlsx`. The CSV is the least-friction path.)*

---

## Step 2 — (Optional) add a Date table for proper time intelligence

**Modeling → New table:**
```DAX
Dates =
ADDCOLUMNS(
    CALENDAR(MIN(finrecon_powerbi[txn_date]), MAX(finrecon_powerbi[txn_date])),
    "Year", YEAR([Date]),
    "MonthNo", MONTH([Date]),
    "Month", FORMAT([Date], "MMM yyyy")
)
```
Relate `Dates[Date]` → `finrecon_powerbi[txn_date]` (Model view, drag to link).

---

## Step 3 — DAX measures

**Modeling → New measure** for each (right-click the table → New measure):

```DAX
Total References = COUNTROWS(finrecon_powerbi)

Total Breaks =
CALCULATE(COUNTROWS(finrecon_powerbi), finrecon_powerbi[is_break] = 1)

Matched =
CALCULATE(COUNTROWS(finrecon_powerbi), finrecon_powerbi[break_type] = "matched")

-- Ledger-side references only (bank-only rows have a blank ledger_amount).
-- Using this as the denominator keeps Match Rate consistent with the pipeline (94.3%).
Ledger References =
CALCULATE(COUNTROWS(finrecon_powerbi), NOT(ISBLANK(finrecon_powerbi[ledger_amount])))

Match Rate % = DIVIDE([Matched], [Ledger References])         -- format as %

Value at Risk = SUM(finrecon_powerbi[value_at_risk])

Auto-cleared % =
DIVIDE(
    CALCULATE(COUNTROWS(finrecon_powerbi), finrecon_powerbi[decision] = "AUTO"),
    [Total Breaks]
)                                                            -- format as %

Human Review Queue =
CALCULATE(
    COUNTROWS(finrecon_powerbi),
    finrecon_powerbi[decision] IN { "HUMAN", "NEEDS_REVIEW" }
)

Avg Confidence =
AVERAGE(finrecon_powerbi[confidence])                        -- format as %
```

---

## Step 4 — Build the visuals (suggested layout)

```
┌───────────────┬───────────────┬───────────────┬───────────────┐
│ Match Rate %  │ Total Breaks  │ Value at Risk │ Human Review  │   <- KPI cards
├───────────────┴───────┬───────┴───────────────┴───────────────┤
│  Breaks by Cause      │  Value at Risk by Month (trend)        │
│  (bar chart)          │  (line/column chart)                   │
├───────────────────────┼────────────────────────────────────────┤
│  Decision mix (donut) │  Approvals queue (table)               │
└───────────────────────┴────────────────────────────────────────┘
   Slicers on the side / top:  currency  |  break_type  |  decision
```

1. **KPI cards** (Card visual): `Match Rate %`, `Total Breaks`, `Value at Risk`,
   `Human Review Queue`.
2. **Breaks by Cause** — Clustered bar chart. Axis = `break_type`,
   Value = `Total Breaks`. Add a visual filter `is_break = 1`.
3. **Value at Risk by Month** — Line chart. Axis = `month` (or `Dates[Month]`),
   Value = `Value at Risk`.
4. **Decision mix** — Donut. Legend = `decision`, Value = `Total References`.
5. **Approvals queue** — Table. Columns: `reference`, `break_type`,
   `value_at_risk`, `llm_category`, `confidence`, `reason`. Filter `decision = "HUMAN"`,
   sort by `value_at_risk` desc.
6. **Aging** (optional) — Table/matrix: `age_days` bucketed vs `Total Breaks`.
7. **Slicers**: `currency`, `break_type`, `decision`.

---

## Step 5 — Polish & save

- Apply a clean theme (**View → Themes**), title the page "FinRecon — Reconciliation Status".
- Format KPI cards; set `Value at Risk` to currency, `Match Rate %`/`Auto-cleared %` to percent.
- **File → Save as** → `powerbi/FinRecon.pbix`.
- **Export → PDF** (or screenshot) into `powerplatform/app_screenshots/` for the repo.

---

## Step 6 — What to screenshot (for the write-up)

- The full dashboard page (KPIs + charts).
- The approvals-queue table (proves the maker-checker/human-in-the-loop control).
- One DAX measure open (proves you built the model, not just dropped fields).

## Notes

- "The dashboard reads the governed output — every row already went through PII
  masking, validation and the human-in-the-loop decision."
- "Match Rate and Value at Risk are the two numbers a reconciliation manager
  watches; the decision donut shows how much the assistant auto-cleared vs
  escalated."
- "The exact figures come from deterministic code (DAX over the reconciled data),
  not the LLM — same principle end to end."
