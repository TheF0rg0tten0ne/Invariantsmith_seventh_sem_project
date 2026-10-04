"""Regression tests for the 'unterminated string literal' failure on converted
Python: a decoded "\\n" inside a string literal became a real line break, and
the verification step then (correctly) rejected the model's attempt to fix it.
The fix is deterministic -- see server/fixer.py::repair_python_strings."""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import error_detector
from server.fixer import (
    repair_python_strings, _try_python_string_repair, _re_escape_newlines_in_strings,
)

FIXTURE = Path(__file__).parent / "fixtures" / "student_manager_broken.py"


def _first_syntax_error(code):
    errs = error_detector.analyze(code, "x.py", "python")
    return next((e for e in errs if e.severity == "syntax"), None)


def test_user_file_reproduces_the_reported_error():
    code = FIXTURE.read_text(encoding="utf-8")
    err = _first_syntax_error(code)
    assert err is not None and "unterminated string literal" in err.message
    assert err.line >= 1


def test_user_file_is_fully_repaired_deterministically():
    code = FIXTURE.read_text(encoding="utf-8")
    err = _first_syntax_error(code)
    result = _try_python_string_repair(code, err.error_type, err.message, "Untitled.py", "python", err.line)
    assert result is not None, "deterministic repair should handle this file"
    assert result.verified is True
    assert result.confidence > 0
    assert result.diff
    # The whole file parses afterwards, not just the first error.
    fixed = repair_python_strings(code)
    ast.parse(fixed)
    # newlines were restored as escapes, not deleted
    assert "print('Database full!\\n')" in fixed
    assert "print('Student added successfully!\\n')" in fixed
    # multi-line f-string (3 physical lines) rejoined
    assert "Student found:\\n{student_to_str(students[index])}\\n" in fixed
    # string that was simply missing its closing quote got closed
    assert fixed.count("def clear_input_buffer") == 1
    assert any(l.rstrip().endswith("{student[\"gpa\"]:.2f}'") for l in fixed.splitlines())
    assert not result.checks[1]["status"] == "fail"


def test_model_path_repairs_decoded_newlines_but_not_missing_quotes():
    # The model-output path only fixes the decode ambiguity.
    joined = _re_escape_newlines_in_strings("print('hi\n')\n", "python")
    assert joined == "print('hi\\n')\n"
    # An f-string the model genuinely forgot to close must stay broken.
    broken = "def f(a):\n    return f\"{a}\n"
    assert _re_escape_newlines_in_strings(broken, "python") == broken


def test_valid_code_is_never_touched():
    ok = "x = 'a'\nprint(\"b\\n\")\ns = '''multi\nline'''\n"
    assert _re_escape_newlines_in_strings(ok, "python") == ok
    assert repair_python_strings(ok) == ok


def test_does_not_glue_unrelated_statements():
    code = "x = 'abc\ny = foo('bar')\n"
    fixed = repair_python_strings(code)
    # x's string is closed in place; y's line is untouched
    assert fixed == "x = 'abc'\ny = foo('bar')\n"
    ast.parse(fixed)


def test_backslash_continuation_and_comments_are_respected():
    code = "x = 'abc' \\\n    'def'\n# it's a comment with a lone quote\ny = 1\n"
    assert repair_python_strings(code) == code


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok:", name)
