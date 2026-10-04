import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.diff_utils import make_diff
from client.diff_view import parse_unified_diff, align_split

CODE = (
    "import json\n\ndef get_user(names, username):\n    for u in names:\n"
    "        if u['username'] == username:\n            return u\n    return bar\n\ndef main():\n    pass\n"
)
FIXED = CODE.replace("return bar", "return None")


def test_parse_numbers_and_signature():
    rows = parse_unified_diff(make_diff(CODE, FIXED, "x.py"), CODE)
    assert rows[0].kind == "hunk"
    assert "def get_user(names, username):" in rows[0].text
    dels = [r for r in rows if r.kind == "del"]
    adds = [r for r in rows if r.kind == "add"]
    assert len(dels) == len(adds) == 1
    assert dels[0].number == adds[0].number == 7
    assert dels[0].text.strip() == "return bar" and adds[0].text.strip() == "return None"
    ctx = [r for r in rows if r.kind == "ctx"]
    assert ctx and ctx[0].number == 4   # numbering follows the file


def test_split_alignment_pads_uneven_blocks():
    old = "a\nb\nc\n"
    new = "a\nX\nY\nZ\nc\n"
    rows = parse_unified_diff(make_diff(old, new, "f.py"), old)
    left, right = align_split(rows)
    assert len(left) == len(right)
    assert any(r.kind == "pad" for r in left)
    assert [r.text for r in right if r.kind == "add"] == ["X", "Y", "Z"]


if __name__ == "__main__":
    test_parse_numbers_and_signature(); test_split_alignment_pads_uneven_blocks(); print("ok")
