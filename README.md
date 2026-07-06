# FinRecon Copilot

**An AI-assisted reconciliation & exception-handling assistant for finance operations.**

FinRecon takes two sources that *should* agree — a general ledger and a
bank/settlement feed — lines them up, finds the **breaks**, uses an LLM to read
the messy human notes explaining each break, and pushes a clean, **approved**
result to a dashboard — all wrapped in bank-grade controls.

> **Design principle:** *rules for the math, AI for the language, human for the
> decisions.* Deterministic code does the exact matching (trustworthy, testable),
> the LLM only reads free text (fuzzy language work), and a person approves
> anything that matters.

Built as a capstone for a **GenAI & Automation Financial Analyst** role — it
touches every line of the JD: SQL, Python, generative AI + prompt engineering,
Microsoft Power Platform, reconciliation, process automation, and
governance/controls.

---

## Architecture (data flows top to bottom)

```
 [ Ledger data ]      [ Bank feed ]        [ Remittance notes ]
 (structured, SQL)                         (unstructured text/PDF)
        \                  |                        |
         v                 v                        v
   PHASE 2/3 : SQL + Python reconcile  ->  list of BREAKS
                          |
                          v
   PHASE 4   : LLM reads each break's note ->
               classify cause + extract fields + summarise (JSON)
                          |
                          v
   PHASE 5   : mask PII -> validate output -> audit log -> human approval
                          |
                          v
   PHASE 6   : Power Automate -> route approval -> email/Teams -> log run
                          |
                          v
   PHASE 7   : Power BI dashboard (match rate, breaks by cause, value at risk)
```

See `docs/architecture.md` and `docs/process_map.md` for the full picture and
the "before vs after" process map.

---

## JD → project map (interview cheat sheet)

| JD requirement                                        | Where it's proven              |
|-------------------------------------------------------|--------------------------------|
| Write SQL for extraction, reconciliation, validation  | Phase 2 — SQL reconciliation   |
| Python scripts for processing, validation, reporting  | Phase 3 — Python pipeline      |
| LLM integration: prompt design, testing, optimization | Phase 4 — GenAI layer + eval   |
| Summarization, classification, information extraction  | Phase 4 — three LLM tasks      |
| Manage structured AND unstructured data               | Phases 1–4 — ledger + notes    |
| Rule-based AND generative AI automation               | Phases 2–4 — rules + AI        |
| Microsoft Power Platform (Automate, Apps, BI)         | Phases 6–7 — flow, app, BI     |
| Controls, governance, compliance, audit docs          | Phase 5 + 8 — controls & docs  |
| Analyze processes, spot automation opportunities      | Phase 0 — process map          |
| Deployment, monitoring, troubleshooting               | Phase 6 — scheduled + alerting |

---

## Folder structure

```
finrecon-copilot/
  data/            ledger.csv, bank_feed.csv, ground_truth.csv, notes/, finrecon.db
  src/
    generate_data.py       (Phase 1)
    reconcile.py           (Phase 3)
    genai.py               (Phase 4)
    governance.py          (Phase 5)
    evaluate_prompts.py    (Phase 4)
  sql/             reconciliation.sql        (Phase 2)
  reports/         exceptions_report.xlsx, audit.log
  powerplatform/   flow_screenshots/, app_screenshots/   (Phase 6)
  powerbi/         FinRecon.pbix             (Phase 7)
  docs/            architecture.md, process_map.md, STAR interview PDF   (Phase 8)
  tests/           test_smoke.py
  config.py        central paths, secrets loader, business rules
  .env.example     copy to .env and add your API key (never commit .env)
  .gitignore  requirements.txt  README.md
```

---

## Getting started

```bash
# 1. Create + activate a virtual environment (Windows / Git Bash)
python -m venv .venv
source .venv/Scripts/activate      # PowerShell: .venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your free LLM API key
cp .env.example .env               # then paste your Gemini or Groq key into .env

# 4. Sanity check
python config.py                   # prints resolved paths + whether a key is set
python -m pytest -q                # smoke tests should pass
```

**Free API key (no credit card):**
- **Gemini** — https://aistudio.google.com/ → *Get API key* → paste into `.env` as `GEMINI_API_KEY`.
- **Groq** — https://console.groq.com/ → *API Keys* → paste into `.env` as `GROQ_API_KEY`.
- **Ollama** (local, private — "no customer data leaves the machine") — https://ollama.com/.

---

## Build order (8 phases)

- [x] **Phase 0** — Setup, accounts, project skeleton, process map *(this scaffold)*
- [x] **Phase 1** — Generate realistic synthetic data (ledger, bank feed, notes) — `src/generate_data.py`
- [x] **Phase 2** — SQL reconciliation in SQLite — `sql/reconciliation.sql`, `src/load_db.py`, `src/reconcile_sql.py`
      *(validated: 72 breaks found, 94.3% match rate, 0 false positives, reversals excluded)*
- [ ] **Phase 3** — Python/pandas pipeline + exceptions report
- [ ] **Phase 4** — GenAI layer (classify / extract / summarise) + eval harness
- [ ] **Phase 5** — Governance: PII masking, validation, audit log, human-in-the-loop
- [ ] **Phase 6** — Power Automate orchestration (schedule, approval, alerting)
- [ ] **Phase 7** — Power BI dashboard (+ optional Power App)
- [ ] **Phase 8** — Docs, GitHub polish, demo video

## Controls (the differentiator)

| Control              | How it's met                                             |
|----------------------|----------------------------------------------------------|
| PII masking          | Names / account numbers stripped **before** the LLM      |
| Output validation    | Every LLM JSON checked (schema, numeric range, category) |
| Human-in-the-loop    | High-value / low-confidence breaks routed for approval   |
| Audit trail          | Every run logs inputs, counts, model, prompts, outputs   |
| Change management    | Git history with meaningful commits, no secrets committed|
