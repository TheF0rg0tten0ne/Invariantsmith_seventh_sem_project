"""
Regression tests for _lenient_parse_fields() / _fix_overescaped_newlines()
in server/fixer.py.

These raw strings are copied verbatim from a real local eval run
(qwen2.5-coder-1.5b-instruct.Q8_0.gguf against data_pipeline/manual_examples/
and data_pipeline/generalization_examples/) that failed with "Model
returned malformed JSON." before this fix. Kept as fixed strings rather
than regenerated so a future refactor can't accidentally "fix" the test
by changing what's being recovered.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.fixer import _lenient_parse_fields, _fix_overescaped_newlines, _parse_model_output


def test_lenient_parse_recovers_unescaped_slash_quote():
    # From 080_unusedvar_staticmethod: model wrote  return "/".join(...)
    # inside fixed_code without escaping the inner quotes.
    raw = ('{"fixed_code": "class PathHelper:\\n    @staticmethod\\n    '
           'def join(base, *parts):\\n        return "/".join([base, *parts])\\n", '
           '"rationale": "separator unused", "confidence": 0.9}')
    parsed = _lenient_parse_fields(raw)
    assert parsed is not None
    assert parsed["fixed_code"] == (
        'class PathHelper:\n    @staticmethod\n    def join(base, *parts):\n'
        '        return "/".join([base, *parts])\n'
    )
    assert parsed["confidence"] == 0.9


def test_lenient_parse_recovers_unescaped_dict_literal():
    # From g06_redef_class_then_function: model wrote a dict literal with
    # unescaped quotes inside fixed_code.
    raw = ('{"fixed_code": "def f():\\n    return {"a": 1}\\n", '
           '"rationale": "x", "confidence": 0.95}')
    parsed = _lenient_parse_fields(raw)
    assert parsed is not None
    assert parsed["fixed_code"] == 'def f():\n    return {"a": 1}\n'


def test_lenient_parse_returns_none_when_keys_missing():
    # No "rationale" key at all -- this is a different, unpredictable
    # failure mode; the lenient parser should refuse to guess.
    raw = '{"fixed_code": "def f(): pass", "confidence": 0.9}'
    assert _lenient_parse_fields(raw) is None


def test_fix_overescaped_newlines_converts_when_no_real_newlines_present():
    # From g14: model emitted \\n (backslash + literal n) instead of an
    # actual newline -- valid JSON, invalid Python.
    code = 'class Plugin(name="plugin_name"):\\n    version = "1.0"\\n'
    fixed = _fix_overescaped_newlines(code)
    assert fixed == 'class Plugin(name="plugin_name"):\n    version = "1.0"\n'


def test_fix_overescaped_newlines_leaves_real_multiline_code_alone():
    code = 'def f():\n    return 1\n'
    assert _fix_overescaped_newlines(code) == code


def test_parse_model_output_recovers_genuinely_correct_fix_from_malformed_json():
    # End-to-end: 080's raw model output should now verify successfully
    # instead of being discarded as "malformed JSON".
    original = (
        'class PathHelper:\n'
        '    @staticmethod\n'
        '    def join(base, *parts):\n'
        '        separator = "/"\n'
        '        return "/".join([base, *parts])\n'
    )
    raw = ('{"fixed_code": "class PathHelper:\\n    @staticmethod\\n    '
           'def join(base, *parts):\\n        return "/".join([base, *parts])\\n", '
           '"rationale": "separator unused", "confidence": 0.9}')
    result = _parse_model_output(
        raw, original, "buffer.py",
        error_type="UnusedVariable",
        error_message="local variable 'separator' is assigned to but never used",
    )
    assert result.verified is True
    assert result.confidence > 0.0
    assert "recovered from malformed JSON" in result.rationale


def test_parse_model_output_still_rejects_genuinely_broken_model_code():
    # 078's raw output recovers cleanly (fixed_code extracted correctly),
    # but the model's own code never closes the f-string -- that's a real
    # bug in the model's output, and should still fail verification
    # rather than being silently "fixed" further.
    original = (
        'def format_price(amount):\n'
        '    currency_symbol = "$"\n'
        '    return f"${amount:.2f}"\n'
    )
    raw = ('{"fixed_code": "def format_price(amount):\\n    return f"${amount:.2f}\\n", '
           '"rationale": "currency_symbol unused", "confidence": 0.95}')
    result = _parse_model_output(
        raw, original, "buffer.py",
        error_type="UnusedVariable",
        error_message="local variable 'currency_symbol' is assigned to but never used",
    )
    assert result.verified is False
    assert "syntax error" in result.rationale


def _run_all():
    tests = [obj for name, obj in globals().items()
             if name.startswith("test_") and callable(obj)]
    for t in tests:
        t()
        print(f"  ok: {t.__name__}")
    print(f"All {len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
