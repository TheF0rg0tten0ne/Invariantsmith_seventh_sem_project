import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.fixer import _parse_model_output

ORIGINAL = "def foo():\n    return bar\n"
ERROR_TYPE = "NameError"
ERROR_MESSAGE = "undefined name 'bar'"


def _raw(fixed_code: str, rationale: str, confidence: float) -> str:
    # fixer.py's contract is "fixed_code" = the ENTIRE corrected file, not a
    # unified diff -- the server computes the diff itself via difflib once a
    # fix is verified. See server/fixer.py's system prompt / _parse_model_output.
    return json.dumps({"fixed_code": fixed_code, "rationale": rationale, "confidence": confidence})


def test_genuine_fix_is_verified_and_trusted():
    raw = _raw(
        "def foo():\n    bar = 1\n    return bar\n",
        "defines bar before returning it", 1.0,
    )
    result = _parse_model_output(raw, ORIGINAL, "test.py", ERROR_TYPE, ERROR_MESSAGE)
    assert result.verified is True
    assert result.confidence == 1.0
    assert result.diff  # kept


def test_noop_fix_is_rejected_despite_high_self_reported_confidence():
    raw = _raw(
        "def foo():\n    return bar  # comment\n",
        "added a comment", 0.9,
    )
    result = _parse_model_output(raw, ORIGINAL, "test.py", ERROR_TYPE, ERROR_MESSAGE)
    assert result.verified is False
    assert result.confidence == 0.0
    assert result.diff == ""


def test_syntax_breaking_fix_is_rejected():
    raw = _raw(
        "def foo(:\n    return 1\n",
        "oops", 0.8,
    )
    result = _parse_model_output(raw, ORIGINAL, "test.py", ERROR_TYPE, ERROR_MESSAGE)
    assert result.verified is False
    assert result.confidence == 0.0


def test_echoed_code_with_no_diff_markers_is_rejected():
    raw = _raw(ORIGINAL, "fixed it", 1.0)
    result = _parse_model_output(raw, ORIGINAL, "test.py", ERROR_TYPE, ERROR_MESSAGE)
    assert result.verified is False
    assert result.confidence == 0.0
    assert result.diff == ""


def test_fix_that_resolves_error_but_leaves_a_pre_existing_one_gets_partial_confidence():
    # original already has an unrelated pre-existing issue (unused import)
    # alongside the NameError; the fix resolves the NameError but doesn't
    # touch the pre-existing one -- that should verify (the targeted error
    # really is gone) but only at partial confidence (something's still
    # not clean about the file).
    original_with_preexisting_issue = "import os\ndef foo():\n    return bar\n"
    raw = _raw(
        "import os\ndef foo():\n    bar = 1\n    return bar\n",
        "defines bar before returning it", 1.0,
    )
    result = _parse_model_output(raw, original_with_preexisting_issue, "test.py", ERROR_TYPE, ERROR_MESSAGE)
    assert result.verified is True
    assert result.confidence <= 0.5  # capped down, not full trust
    assert result.diff  # still returned since original error IS fixed


if __name__ == "__main__":
    test_genuine_fix_is_verified_and_trusted()
    test_noop_fix_is_rejected_despite_high_self_reported_confidence()
    test_syntax_breaking_fix_is_rejected()
    test_echoed_code_with_no_diff_markers_is_rejected()
    test_fix_that_resolves_error_but_leaves_a_pre_existing_one_gets_partial_confidence()
    print("All tests passed.")
