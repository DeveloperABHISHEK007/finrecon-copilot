"""Phase 4 tests - GenAI parsing/validation + offline eval harness (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import genai, evaluate_prompts as ev


def test_extract_json_handles_code_fences():
    assert genai._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert genai._extract_json('noise {"category":"TIMING"} tail')["category"] == "TIMING"


def test_classification_validation_normalises_and_bounds():
    out = genai.classify_note(
        "amount keyed wrong",
        complete_fn=lambda _p: '{"category":"data_error","confidence":1.4}')
    assert out["category"] == "DATA_ERROR"      # upper-cased
    assert out["confidence"] == 1.0             # clamped to [0,1]


def test_bad_category_is_rejected():
    import pytest
    with pytest.raises(Exception):
        genai.classify_note("x", complete_fn=lambda _p: '{"category":"BANANA"}')


def test_offline_v2_beats_v1_on_labelled_notes():
    import pytest

    import config
    if not config.GROUND_TRUTH_CSV.exists():
        pytest.skip("no labelled ground_truth.csv (provided-data mode) - run "
                    "src.generate_data for the synthetic benchmark")
    df = ev.load_labelled()
    v1 = ev.run_version(df, "v1", live=False)["accuracy"]
    v2 = ev.run_version(df, "v2", live=False)["accuracy"]
    assert v2 >= v1
    assert v2 > 90.0
