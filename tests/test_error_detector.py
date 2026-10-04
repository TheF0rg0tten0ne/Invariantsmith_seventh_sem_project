import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.error_detector import analyze, check_syntax, check_lint


def test_syntax_error_detected():
    code = "def foo(:\n    pass\n"
    err = check_syntax(code)
    assert err is not None
    assert err.error_type == "SyntaxError"


def test_valid_syntax_passes():
    code = "def foo():\n    pass\n"
    assert check_syntax(code) is None


def test_undefined_name_detected():
    code = "def foo():\n    return bar\n"
    errors = check_lint(code)
    assert any(e.error_type == "NameError" for e in errors)


def test_unused_import_detected():
    code = "import os\n\ndef foo():\n    return 1\n"
    errors = check_lint(code)
    assert any(e.error_type == "UnusedImport" for e in errors)


def test_analyze_short_circuits_on_syntax_error():
    code = "def foo(:\n    return bar\n"
    errors = analyze(code)
    assert len(errors) == 1
    assert errors[0].error_type == "SyntaxError"


if __name__ == "__main__":
    test_syntax_error_detected()
    test_valid_syntax_passes()
    test_undefined_name_detected()
    test_unused_import_detected()
    test_analyze_short_circuits_on_syntax_error()
    print("All tests passed.")
