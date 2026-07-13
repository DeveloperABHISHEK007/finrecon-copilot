# FinRecon Copilot — Architecture

## End-to-end pipeline

```
 [ Ledger data ]      [ Bank feed ]        [ Remittance notes ]
 (structured, SQL)    (structured)         (unstructured text/PDF)
        \                  |                        |
         \                 |                        |
          v                v                        v
   ┌─────────────────────────────────┐             │
   │ PHASE 2/3  SQL + Python reconcile│             │
   │  full-outer-join on reference    │             │
   │  -> matched / ledger-only /      │             │
   │     bank-only / amount-mismatch  │             │
   └───────────────┬─────────────────┘             │
                   │  list of BREAKS                │
                   v                                v
        ┌────────────────────────────────────────────────┐
        │ PHASE 4  LLM (temperature 0)                     │
        │  classify cause  (TIMING/DUPLICATE/DATA_ERROR/   │
        │                   MISSING)                       │
        │  extract fields  (reference, amount, date)       │
        │  summarise day   (manager narrative)   -> JSON   │
        └───────────────────┬──────────────────────────────┘
                            v
        ┌────────────────────────────────────────────────┐
        │ PHASE 5  Governance                              │
        │  mask PII -> validate JSON -> audit log ->       │
        │  human-in-the-loop approval (maker-checker)      │
        └───────────────────┬──────────────────────────────┘
                            v
        ┌────────────────────────────────────────────────┐
        │ PHASE 6  Power Automate                          │
        │  scheduled trigger -> approval routing ->        │
        │  email/Teams notify -> error handling -> log run │
        └───────────────────┬──────────────────────────────┘
                            v
        ┌────────────────────────────────────────────────┐
        │ PHASE 7  Power BI dashboard (+ optional Power App)│
        │  match rate • breaks by cause • value at risk •  │
        │  aging / trend                                   │
        └────────────────────────────────────────────────┘
```

## Division of labour

| Layer            | Owner              | Why                                            |
|------------------|--------------------|------------------------------------------------|
| Exact matching   | Deterministic code | Trustworthy, testable, auditable — never an LLM|
| Math / totals    | Deterministic code | Must be exactly right and reproducible         |
| Reading notes    | LLM (temp 0)       | Fuzzy natural-language work only               |
| Decisions        | Human              | Approves high-value / low-confidence breaks    |

**One sentence:** *rules for the math, AI for the language, human for the decisions.*

## Break types

| Break            | Meaning                                             |
|------------------|-----------------------------------------------------|
| missing-in-bank  | In the ledger, not in the bank feed                 |
| missing-in-ledger| In the bank feed, not in the ledger                 |
| amount-mismatch  | Same reference, different amount (e.g. 9,000/90,000)|
| duplicate        | Same reference booked more than once                |
| reversal         | A retry/reversal pair — excluded before aggregating |
