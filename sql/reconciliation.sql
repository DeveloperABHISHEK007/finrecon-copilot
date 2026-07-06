-- ═══════════════════════════════════════════════════════════════════════
-- FinRecon Copilot - Phase 2: SQL reconciliation (the rule-based core)
-- ═══════════════════════════════════════════════════════════════════════
-- Input tables (loaded by src/load_db.py):
--     ledger(reference, txn_date, amount, account, currency)   -- one row/ref
--     bank_feed(reference, txn_date, amount, account, currency)-- breaks injected
--
-- Output objects created here:
--     reversals      (view)  - references to exclude (self-cancelling +/- pairs)
--     bank_summary   (view)  - bank feed collapsed to one row per reference
--     recon_result   (table) - every reference classified (incl. 'matched')
--     breaks         (view)  - recon_result minus 'matched'
--
-- Design note: rules do the exact matching and math here - deterministic,
-- testable, auditable. The LLM never touches this part (that's Phase 4).
-- Run this whole file with:  python src/reconcile_sql.py
-- ═══════════════════════════════════════════════════════════════════════

-- Clean slate so the script is safe to re-run (idempotent).
DROP VIEW  IF EXISTS breaks;
DROP TABLE IF EXISTS recon_result;
DROP VIEW  IF EXISTS bank_summary;
DROP VIEW  IF EXISTS reversals;

-- ───────────────────────────────────────────────────────────────────────
-- (0) REVERSALS / RETRIES  -  exclude before aggregating.
-- A reversal is a reference whose bank rows net to ~0 across 2+ entries
-- (a payment that was posted then reversed, or a failed retry). These are
-- NOT breaks and must not be counted as "missing in ledger", so we identify
-- them first and drop them from everything downstream.
-- ───────────────────────────────────────────────────────────────────────
CREATE VIEW reversals AS
SELECT reference
FROM bank_feed
GROUP BY reference
HAVING ABS(SUM(amount)) < 0.01      -- nets to zero
   AND COUNT(*) >= 2;               -- across at least two entries

-- ───────────────────────────────────────────────────────────────────────
-- (1) BANK SUMMARY  -  collapse the bank feed to one row per reference,
-- excluding reversals. bank_rows lets us spot duplicates; bank_amount is the
-- per-line amount (duplicate lines are identical, so MIN = the real amount).
-- ───────────────────────────────────────────────────────────────────────
CREATE VIEW bank_summary AS
SELECT reference,
       COUNT(*)      AS bank_rows,     -- >1 means duplicate posting
       MIN(amount)   AS bank_amount,   -- representative per-line amount
       SUM(amount)   AS bank_sum,      -- kept for auditing
       MAX(currency) AS currency
FROM bank_feed
WHERE reference NOT IN (SELECT reference FROM reversals)
GROUP BY reference;

-- ───────────────────────────────────────────────────────────────────────
-- (2) RECONCILE  -  emulate a FULL OUTER JOIN on reference with
--     (ledger LEFT JOIN bank)  UNION ALL  (bank-only rows).
-- SQLite >= 3.39 supports FULL OUTER JOIN natively, but the LEFT JOIN + UNION
-- pattern works on every version and is the classic reconciliation idiom.
-- Each reference is then classified with a single CASE expression.
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE recon_result AS
WITH full_outer AS (
    -- Left side: every ledger reference, with its bank match if any.
    SELECT l.reference       AS reference,
           l.amount          AS ledger_amount,
           b.bank_amount     AS bank_amount,
           b.bank_rows       AS bank_rows,
           l.currency        AS currency
    FROM ledger l
    LEFT JOIN bank_summary b ON l.reference = b.reference

    UNION ALL

    -- Right-only side: bank references with no ledger match at all.
    SELECT b.reference       AS reference,
           NULL              AS ledger_amount,
           b.bank_amount     AS bank_amount,
           b.bank_rows       AS bank_rows,
           b.currency        AS currency
    FROM bank_summary b
    LEFT JOIN ledger l ON b.reference = l.reference
    WHERE l.reference IS NULL
)
SELECT
    reference,
    ledger_amount,
    bank_amount,
    currency,
    -- Classify the reference. Order matters: existence first, then dup, then value.
    CASE
        WHEN bank_amount   IS NULL THEN 'missing-in-bank'
        WHEN ledger_amount IS NULL THEN 'missing-in-ledger'
        WHEN bank_rows > 1         THEN 'duplicate'
        WHEN ABS(ledger_amount - bank_amount) > 0.01 THEN 'amount-mismatch'
        ELSE 'matched'
    END AS break_type,
    -- Signed difference where both sides exist (bank - ledger).
    CASE WHEN ledger_amount IS NOT NULL AND bank_amount IS NOT NULL
         THEN ROUND(bank_amount - ledger_amount, 2) END AS amount_diff,
    -- Value at risk = the money exposed by this break.
    ROUND(CASE
        WHEN bank_amount   IS NULL THEN ledger_amount              -- missing-in-bank
        WHEN ledger_amount IS NULL THEN bank_amount                -- missing-in-ledger
        WHEN bank_rows > 1         THEN bank_amount                -- duplicate value
        WHEN ABS(ledger_amount - bank_amount) > 0.01
             THEN ABS(bank_amount - ledger_amount)                 -- mismatch delta
        ELSE 0
    END, 2) AS value_at_risk
FROM full_outer;

-- The breaks table the rest of the project queries (matched rows removed).
CREATE VIEW breaks AS
SELECT * FROM recon_result WHERE break_type <> 'matched';

-- ───────────────────────────────────────────────────────────────────────
-- (3) SUMMARY QUERIES  -  run these to see the result. The Python runner
-- prints them; you can also paste them into DB Browser.
-- ───────────────────────────────────────────────────────────────────────

-- 3a. Breaks by type: how many and how much money is at risk.
--     SELECT break_type,
--            COUNT(*)              AS n,
--            ROUND(SUM(value_at_risk), 2) AS value_at_risk
--     FROM breaks
--     GROUP BY break_type
--     ORDER BY n DESC;

-- 3b. Match rate: matched ledger references / all ledger references.
--     SELECT
--       (SELECT COUNT(*) FROM recon_result WHERE break_type = 'matched')  AS matched,
--       (SELECT COUNT(*) FROM ledger)                                     AS ledger_total,
--       ROUND(100.0 * (SELECT COUNT(*) FROM recon_result WHERE break_type='matched')
--                    / (SELECT COUNT(*) FROM ledger), 2)                  AS match_rate_pct;

-- 3c. Reversals excluded (reported, not counted as breaks).
--     SELECT COUNT(*) AS reversal_refs_excluded FROM reversals;
