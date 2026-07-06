"""Phase 5 tests - the four governance controls (all offline, no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from src import governance as gov


# Control 1 - masking
def test_mask_pii_redacts_account_email_keeps_reference_and_date():
    text = "pay REF-000113 on 2026-06-20, acct AC-12345678, ping jo@bank.com"
    masked, n = gov.mask_pii(text)
    assert "[ACCT]" in masked and "[EMAIL]" in masked
    assert "REF-000113" in masked          # reference NOT masked (needed to match)
    assert "2026-06-20" in masked          # ISO date NOT mistaken for a phone
    assert n >= 2


# Control 2 - validation + quarantine
def test_validate_classification_accepts_good_rejects_bad():
    ok, _ = gov.validate_classification({"category": "TIMING", "confidence": 0.9})
    assert ok
    bad, errs = gov.validate_classification({"category": "BANANA", "confidence": 2})
    assert not bad and errs


def test_validate_extraction_range_and_date():
    ok, _ = gov.validate_extraction({"amount": 100.0, "date": "2026-01-02"})
    assert ok
    bad, errs = gov.validate_extraction({"amount": -5, "date": "not-a-date"})
    assert not bad and len(errs) == 2


# Control 4 - routing (maker-checker)
def test_route_high_value_low_confidence_and_invalid():
    assert gov.route(config.HIGH_VALUE_THRESHOLD + 1, 1.0, True) == ("HUMAN", "high-value")
    assert gov.route(0.0, 0.10, True) == ("HUMAN", "low-confidence")
    assert gov.route(0.0, 1.0, False) == ("QUARANTINE", "failed-output-validation")
    assert gov.route(0.0, 1.0, True) == ("AUTO", "auto-cleared")


# Control 3 - audit log writes structured records
def test_audit_log_writes_jsonl(tmp_path):
    import json
    p = tmp_path / "audit.log"
    a = gov.AuditLog(path=p, run_id="test-run")
    a.record("break_processed", reference="REF-1", decision="AUTO")
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    assert rec["run_id"] == "test-run" and rec["event"] == "break_processed"
    assert "ts" in rec
