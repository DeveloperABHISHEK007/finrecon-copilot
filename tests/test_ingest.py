"""Tests for the bring-your-own-data ingester (column mapping + cleaning)."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import ingest


def test_detect_columns_handles_aliases_and_spacing():
    df = pd.DataFrame(columns=["Txn Ref", "Value Date", "Paid Amount",
                               "GL Account", "Ccy", "Remittance Note"])
    m = ingest.detect_columns(df)
    assert m["reference"] == "Txn Ref"
    assert m["amount"] == "Paid Amount"
    assert m["txn_date"] == "Value Date"
    assert m["note"] == "Remittance Note"


def test_clean_amount_strips_symbols_commas_and_parens():
    s = pd.Series([" $1,250.00 ", "3,400.00", "(500)", "€9000", "bad"])
    out = ingest.clean_amount(s)
    assert out[0] == 1250.0
    assert out[1] == 3400.0
    assert out[2] == -500.0
    assert out[3] == 9000.0
    assert pd.isna(out[4])          # unparseable -> NaN


def test_clean_frame_produces_canonical_schema():
    df = pd.DataFrame({
        "Reference": ["inv-1", "INV-2"],
        "Posting Date": ["01 Jun 2026", "2026/06/02"],
        "Paid Amount": ["$1,000.00", "2000"],
        "Account No": ["ACC55010", "ACC55011"],
        "Currency": ["usd", "USD"],
    })
    out, note_col = ingest.clean_frame(df, "bank")
    assert list(out.columns) == ["reference", "txn_date", "amount", "account", "currency"]
    assert out.loc[0, "reference"] == "INV-1"       # upper-cased
    assert out.loc[0, "amount"] == 1000.0            # symbol/comma stripped
    assert out.loc[0, "currency"] == "USD"
    assert note_col is None


def test_missing_required_column_raises():
    import pytest
    df = pd.DataFrame({"date": ["2026-01-01"], "memo": ["x"]})  # no reference/amount
    with pytest.raises(ValueError):
        ingest.clean_frame(df, "ledger")
