import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.diff_utils import make_diff, apply_diff


def test_make_and_apply_roundtrip():
    original = "def foo():\n    return bar\n"
    fixed = "def foo():\n    return 1\n"
    diff = make_diff(original, fixed)
    result = apply_diff(original, diff)
    assert result == fixed, f"Roundtrip failed.\nGot:\n{result}\nExpected:\n{fixed}"


def test_no_change_diff_is_empty():
    original = "x = 1\n"
    diff = make_diff(original, original)
    assert diff == ""


if __name__ == "__main__":
    test_make_and_apply_roundtrip()
    test_no_change_diff_is_empty()
    print("All tests passed.")
