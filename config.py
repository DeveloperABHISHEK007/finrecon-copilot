"""
FinRecon Copilot — central configuration.

One place for every path and setting. Nothing else in the project should
hard-code a file path or read os.environ directly — import from here.

Secrets come from a .env file (see .env.example) and are loaded once here.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# --- Paths -------------------------------------------------------------
# PROJECT_ROOT is the folder this file lives in.
PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
NOTES_DIR = DATA_DIR / "notes"
SQL_DIR = PROJECT_ROOT / "sql"
REPORTS_DIR = PROJECT_ROOT / "reports"
DOCS_DIR = PROJECT_ROOT / "docs"

# Key data files (created in later phases)
LEDGER_CSV = DATA_DIR / "ledger.csv"
BANK_FEED_CSV = DATA_DIR / "bank_feed.csv"
GROUND_TRUTH_CSV = DATA_DIR / "ground_truth.csv"
DB_PATH = DATA_DIR / "finrecon.db"
DB_URL = f"sqlite:///{DB_PATH}"

EXCEPTIONS_REPORT = REPORTS_DIR / "exceptions_report.xlsx"
AUDIT_LOG = REPORTS_DIR / "audit.log"

# Make sure the output folders exist so later phases never crash on write.
for _d in (DATA_DIR, NOTES_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Secrets / LLM settings -------------------------------------------
load_dotenv(PROJECT_ROOT / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

# --- Reconciliation business rules ------------------------------------
# A break above this value is "high-value" and must go to a human (Phase 5).
HIGH_VALUE_THRESHOLD = 10_000.0

# Amount differences below this are treated as a match (rounding tolerance).
AMOUNT_TOLERANCE = 0.01

# Allowed LLM classification labels (Phase 4/5 validation).
ALLOWED_CATEGORIES = ("TIMING", "DUPLICATE", "DATA_ERROR", "MISSING")


def active_llm_key() -> str | None:
    """Return the API key for whichever provider is selected."""
    return {
        "gemini": GEMINI_API_KEY,
        "groq": GROQ_API_KEY,
        "ollama": "local",  # no key needed
    }.get(LLM_PROVIDER)


if __name__ == "__main__":
    # Quick sanity check:  python config.py
    print(f"PROJECT_ROOT     : {PROJECT_ROOT}")
    print(f"LLM_PROVIDER     : {LLM_PROVIDER}")
    print(f"LLM key present  : {bool(active_llm_key() and active_llm_key() != 'your-gemini-key-here')}")
    print(f"DB_URL           : {DB_URL}")
