"""Smoke tests — keep the repo green from day one (Phase 0)."""

import sys
from pathlib import Path

# Make the project root importable (config.py lives there).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config


def test_config_imports_and_paths_resolve():
    assert config.PROJECT_ROOT.exists()
    assert config.DATA_DIR.exists()
    assert config.REPORTS_DIR.exists()
    assert config.DB_URL.startswith("sqlite:///")


def test_business_rules_present():
    assert config.HIGH_VALUE_THRESHOLD > 0
    assert set(config.ALLOWED_CATEGORIES) == {"TIMING", "DUPLICATE", "DATA_ERROR", "MISSING"}


def test_llm_provider_is_known():
    assert config.LLM_PROVIDER in {"gemini", "groq", "ollama"}
