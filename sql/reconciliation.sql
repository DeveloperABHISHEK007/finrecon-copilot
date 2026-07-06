-- ═══════════════════════════════════════════════════════════════════════
-- FinRecon Copilot — Phase 2: SQL reconciliation (the rule-based core)
-- ═══════════════════════════════════════════════════════════════════════
-- Load ledger.csv and bank_feed.csv into SQLite (via SQLAlchemy or DB Browser),
-- then use these queries to find every break. SQLite has no FULL OUTER JOIN, so
-- we emulate it with LEFT JOIN + UNION. Filled in during Phase 2.
--
-- Tables expected:
--   ledger(reference, txn_date, amount, account, currency)
--   bank_feed(reference, txn_date, amount, account, currency)
-- ═══════════════════════════════════════════════════════════════════════

-- (1) Missing on either side + amount mismatches (emulated FULL OUTER JOIN)
-- TODO Phase 2:
--   SELECT ... FROM ledger l LEFT JOIN bank_feed b ON l.reference = b.reference
--   UNION
--   SELECT ... FROM bank_feed b LEFT JOIN ledger l ON b.reference = l.reference
--   WHERE l.reference IS NULL;

-- (2) Duplicates
-- TODO Phase 2:
--   SELECT reference, COUNT(*) AS n FROM ledger GROUP BY reference HAVING COUNT(*) > 1;

-- (3) Exclude reversals/retries before aggregating
-- TODO Phase 2.

-- (4) Summary: match rate + count/value of breaks by type
-- TODO Phase 2.
