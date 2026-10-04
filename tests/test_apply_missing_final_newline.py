"""Regression: Apply returned 409 stale_diff for model fixes whenever the editor
buffer had no trailing newline but the model's fixed code did. difflib glued the
removed and added last lines together (`-}+}`), so apply_diff could never match.
See server/diff_utils.py (_ensure_final_newline / _eq_ignoring_final_newline)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.diff_utils import make_diff, apply_diff

BUFFER_NO_EOL = (
    '#include <stdio.h>\n'
    'int main() {\n'
    '    int n;\n'
    '    scanf("%d", n);\n'
    '    return 0;\n'
    '}'
)
MODEL_FIX_WITH_EOL = BUFFER_NO_EOL.replace('scanf("%d", n);', 'scanf("%d", &n);') + '\n'


def test_diff_has_no_glued_rows():
    d = make_diff(BUFFER_NO_EOL, MODEL_FIX_WITH_EOL, "Untitled")
    assert "}+}" not in d
    assert "-    scanf(\"%d\", n);\n+    scanf(\"%d\", &n);\n" in d


def test_model_fix_applies_to_buffer_without_trailing_newline():
    d = make_diff(BUFFER_NO_EOL, MODEL_FIX_WITH_EOL, "Untitled")
    out = apply_diff(BUFFER_NO_EOL, d)
    assert out.rstrip("\n") == MODEL_FIX_WITH_EOL.rstrip("\n")


def test_unchanged_last_line_keeps_buffer_style():
    d = make_diff(BUFFER_NO_EOL, BUFFER_NO_EOL.replace("n);", "&n);"), "Untitled")
    assert apply_diff(BUFFER_NO_EOL, d).endswith("}")


def test_insert_after_last_line_without_eol():
    assert apply_diff("a\nb", make_diff("a\nb", "a\nb\nc\n", "f")) == "a\nb\nc\n"


def test_crlf_still_strict():
    orig = "x\r\ny\r\n"
    assert apply_diff(orig, make_diff(orig, "x\r\nZ\r\n", "f")) == "x\r\nZ\r\n"
