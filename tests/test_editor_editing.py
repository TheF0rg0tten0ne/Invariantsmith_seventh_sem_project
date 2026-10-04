"""Editor behaviour driven through real key events (offscreen Qt)."""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from client.editor_widget import CodeEditor
from client.theme import Theme

ROOT = os.path.join(os.path.dirname(__file__), "..")


class _Api:
    def analyze(self, *a, **k):
        return {"errors": [], "detected_language": "python"}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make(app):
    made = []

    def _make(lang="c", text=""):
        ed = CodeEditor(_Api())
        with open(os.path.join(ROOT, "themes", "dark.json")) as f:
            ed.set_theme(Theme(json.load(f)))
        ed.resize(700, 400)
        ed.show()
        ed.set_language(lang)
        ed.setPlainText(text)
        ed.moveCursor(ed.textCursor().MoveOperation.End)
        made.append(ed)
        return ed

    yield _make
    for ed in made:
        ed._debounce_timer.stop()
        ed.close()


def typ(ed, s):
    for ch in s:
        if ch == "\n":
            QTest.keyClick(ed, Qt.Key.Key_Return)
        elif ch == "\t":
            QTest.keyClick(ed, Qt.Key.Key_Tab)
        else:
            QTest.keyClicks(ed, ch)


def key(ed, k, mod=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(ed, k, mod)


def caret(ed):
    c = ed.textCursor()
    return c.blockNumber(), c.positionInBlock()


# ---------------------------------------------------------------- pairing --
def test_open_brace_autocloses(make):
    ed = make("c")
    typ(ed, "{")
    assert ed.toPlainText() == "{}" and caret(ed) == (0, 1)


def test_enter_between_braces_opens_block(make):
    ed = make("c")
    typ(ed, "int main() {\n")
    assert ed.toPlainText() == "int main() {\n    \n}"
    assert caret(ed) == (1, 4)


def test_nested_block_keeps_indent(make):
    ed = make("c")
    typ(ed, "void f() {\nif (x) {\n")
    assert ed.toPlainText() == "void f() {\n    if (x) {\n        \n    }\n}"
    assert caret(ed) == (2, 8)


def test_overtype_closer(make):
    ed = make("c")
    typ(ed, "f(a)")
    assert ed.toPlainText() == "f(a)" and caret(ed) == (0, 4)
    typ(ed, ";")
    assert ed.toPlainText() == "f(a);"


def test_does_not_overtype_a_closer_that_was_already_there(make):
    ed = make("c", "foo)")
    ed.moveCursor(ed.textCursor().MoveOperation.StartOfLine)
    for _ in range(3):
        key(ed, Qt.Key.Key_Right)
    typ(ed, ")")
    assert ed.toPlainText() == "foo))"


def test_no_pairing_before_identifier(make):
    ed = make("c", "abc")
    ed.moveCursor(ed.textCursor().MoveOperation.StartOfLine)
    typ(ed, "(")
    assert ed.toPlainText() == "(abc"


def test_quotes_pair_and_overtype(make):
    ed = make("c")
    typ(ed, 'puts("hi")')
    assert ed.toPlainText() == 'puts("hi")'
    assert caret(ed) == (0, 10)


def test_apostrophe_after_letter_is_plain(make):
    ed = make("python")
    typ(ed, "x = \"don't\"")
    assert ed.toPlainText() == "x = \"don't\""


def test_no_pairing_inside_comment_or_string(make):
    ed = make("python")
    typ(ed, "# note (")
    assert ed.toPlainText() == "# note ("
    ed2 = make("c")
    typ(ed2, 'puts("a (')
    assert ed2.toPlainText().count(")") == 1       # only puts('s own closer; none added inside the string


def test_python_triple_quotes(make):
    ed = make("python")
    typ(ed, '"""')
    assert ed.toPlainText() == '""""""' and caret(ed) == (0, 3)


def test_surround_selection(make):
    ed = make("c", "abc")
    ed.selectAll()
    typ(ed, "(")
    assert ed.toPlainText() == "(abc)"
    assert ed.textCursor().selectedText() == "abc"
    typ(ed, '"')
    assert ed.toPlainText() == '("abc")'


def test_backspace_removes_empty_pair(make):
    ed = make("c")
    typ(ed, "[")
    assert ed.toPlainText() == "[]"
    key(ed, Qt.Key.Key_Backspace)
    assert ed.toPlainText() == ""


def test_auto_close_can_be_disabled(make):
    ed = make("c")
    ed.apply_settings(auto_close=False)
    typ(ed, "(")
    assert ed.toPlainText() == "("


def test_closing_brace_dedents_to_its_opener(make):
    ed = make("c")
    ed.apply_settings(auto_close=False)
    typ(ed, "if (x) {\nfoo();\n}")
    assert ed.toPlainText() == "if (x) {\n    foo();\n}"


# ------------------------------------------------------ indentation / python --
def test_python_else_dedents_on_colon(make):
    ed = make("python")
    typ(ed, "if x:\npass\nelse:")
    assert ed.toPlainText() == "if x:\n    pass\nelse:"


def test_python_enter_after_colon_and_after_return(make):
    ed = make("python")
    typ(ed, "def f():\nreturn 1\n")
    assert ed.toPlainText() == "def f():\n    return 1\n"
    assert caret(ed) == (2, 0)


def test_python_enter_inside_brackets(make):
    ed = make("python")
    typ(ed, "x = [\n")
    assert ed.toPlainText() == "x = [\n    \n]"


def test_block_comment_continuation(make):
    ed = make("java")
    typ(ed, "/**\n")
    assert ed.toPlainText() == "/**\n * \n */"
    assert caret(ed) == (1, 3)


def test_case_label_indents(make):
    ed = make("c")
    ed.apply_settings(auto_close=False)
    typ(ed, "case 1:\n")
    assert ed.toPlainText() == "case 1:\n    "


# ----------------------------------------------------------- completion --
def test_popup_opens_and_tab_accepts_include(make):
    ed = make("c")
    typ(ed, "#inc")
    assert ed._popup.isVisible()
    assert ed._popup.current_completion().label.startswith("#include")
    key(ed, Qt.Key.Key_Down)                      # pick the first concrete header line
    c = ed._popup.current_completion()
    key(ed, Qt.Key.Key_Tab)
    assert ed.toPlainText() == c.body
    assert not ed._popup.isVisible()


def test_include_header_inside_angle_brackets(make):
    ed = make("c")
    typ(ed, "#include <std")
    assert ed.toPlainText() == "#include <std>"       # `<` auto-closed
    assert ed._popup.isVisible()
    assert ed._popup.current_completion().label == "stdio.h"
    key(ed, Qt.Key.Key_Tab)
    assert ed.toPlainText() == "#include <stdio.h>"
    assert caret(ed) == (0, len("#include <stdio.h>"))   # caret stepped past '>'


def test_typing_a_full_include_line_leaves_no_stray_bracket(make):
    ed = make("c")
    typ(ed, "#include <stdio.h>\nint x;")
    assert ed.toPlainText() == "#include <stdio.h>\nint x;"
    ed2 = make("c")
    typ(ed2, '#include "util.h"\n')
    assert ed2.toPlainText() == '#include "util.h"\n'


def test_escape_closes_popup_without_inserting(make):
    ed = make("python")
    typ(ed, "pri")
    assert ed._popup.isVisible()
    key(ed, Qt.Key.Key_Escape)
    assert not ed._popup.isVisible() and ed.toPlainText() == "pri"


def test_enter_on_finished_word_is_just_a_newline(make):
    ed = make("python")
    typ(ed, "def f():\npass")
    key(ed, Qt.Key.Key_Return)
    assert ed.toPlainText() == "def f():\n    pass\n"     # no completion was swallowed by Enter
    assert not ed._popup.isVisible()


def test_for_snippet_mirrors_and_tab_stops(make):
    ed = make("c")
    typ(ed, "for")
    assert ed._popup.current_completion().label == "for"
    key(ed, Qt.Key.Key_Tab)
    assert ed.toPlainText().startswith("for (int i = 0; i < n; i++) {")
    assert ed.textCursor().selectedText() == "i"
    typ(ed, "k")                                      # rename the loop variable
    assert ed.toPlainText().startswith("for (int k = 0; k < n; k++) {")
    key(ed, Qt.Key.Key_Tab)
    assert ed.textCursor().selectedText() == "n"
    typ(ed, "len")
    key(ed, Qt.Key.Key_Tab)                           # -> $0 inside the body
    assert ed._snippet is None
    assert ed.toPlainText() == "for (int k = 0; k < len; k++) {\n    \n}"
    assert caret(ed) == (1, 4)


def test_python_def_snippet(make):
    ed = make("python")
    typ(ed, "de")
    key(ed, Qt.Key.Key_Tab)
    assert ed.toPlainText() == "def name(args):\n    pass"
    assert ed.textCursor().selectedText() == "name"
    typ(ed, "go")
    key(ed, Qt.Key.Key_Tab)
    assert ed.textCursor().selectedText() == "args"


def test_snippet_indents_to_current_line(make):
    ed = make("java")
    typ(ed, "class A {\nso")
    key(ed, Qt.Key.Key_Tab)
    assert ed.toPlainText() == "class A {\n    System.out.println();\n}"


def test_function_completion_inserts_parens_and_closer_is_overtyped(make):
    ed = make("python")
    typ(ed, "le")
    labels = []
    while ed._popup.isVisible() and ed._popup.current_completion().label != "len":
        key(ed, Qt.Key.Key_Down)
        labels.append(1)
        assert len(labels) < 30
    key(ed, Qt.Key.Key_Tab)
    assert ed.toPlainText() == "len()"
    typ(ed, "xs)")
    assert ed.toPlainText() == "len(xs)"


def test_ctrl_space_opens_without_prefix(make):
    ed = make("python")
    key(ed, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert ed._popup.isVisible()


def test_suggestions_can_be_disabled(make):
    ed = make("python")
    ed.apply_settings(suggestions=False)
    typ(ed, "pri")
    assert not ed._popup.isVisible()


def test_snippet_session_ends_when_caret_leaves(make):
    ed = make("c")
    typ(ed, "for")
    key(ed, Qt.Key.Key_Tab)
    assert ed._snippet is not None
    ed.moveCursor(ed.textCursor().MoveOperation.End)
    ed.moveCursor(ed.textCursor().MoveOperation.Down)
    typ(ed, "\n\nzz")
    assert ed._snippet is None


# --------------------------------------------------------- line commands --
def test_delete_line(make):
    ed = make("python", "a\nb\nc")
    ed.goto_line(2)
    key(ed, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert ed.toPlainText() == "a\nc"
    ed.goto_line(2)
    ed.delete_line()
    assert ed.toPlainText() == "a"
    ed.delete_line()
    assert ed.toPlainText() == ""


def test_insert_line_below_and_above(make):
    ed = make("python", "    x = 1\n    y = 2")
    ed.goto_line(1)
    key(ed, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert ed.toPlainText() == "    x = 1\n    \n    y = 2" and caret(ed) == (1, 4)
    key(ed, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert ed.toPlainText().split("\n")[1:3] == ["    ", "    "] and caret(ed) == (1, 4)


def test_smart_home_toggles(make):
    ed = make("python", "    code")
    key(ed, Qt.Key.Key_Home)
    assert caret(ed) == (0, 4)
    key(ed, Qt.Key.Key_Home)
    assert caret(ed) == (0, 0)


def test_select_next_occurrence_and_line(make):
    ed = make("python", "foo bar foo")
    ed.goto_line(1, 1)
    key(ed, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert ed.textCursor().selectedText() == "foo"
    key(ed, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert ed.textCursor().selectionStart() == 8


def test_copy_cut_without_selection_uses_whole_line(make, app):
    ed = make("python", "one\ntwo\nthree")
    ed.goto_line(2)
    key(ed, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert app.clipboard().text() == "two\n"
    key(ed, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    assert ed.toPlainText() == "one\nthree"


def test_bracket_match_and_jump(make):
    ed = make("c", "f(a[1])")
    ed.goto_line(1, 2)                       # right after 'f' -> before '('
    pair = ed._find_bracket_pair()
    assert pair == (1, 6)
    ed.goto_matching_bracket()
    assert ed.textCursor().position() == 7


def test_tidy_document(make):
    ed = make("python", "a = 1   \nb = 2\t\n\nc = 3")
    assert ed.tidy_document(ed.current) is True
    assert ed.toPlainText() == "a = 1\nb = 2\n\nc = 3\n"
    assert ed.tidy_document(ed.current) is False


def test_indent_guides_paint_without_error(make, app):
    ed = make("python", "def f():\n    if x:\n\n        return 1\n")
    ed.repaint()
    pm = ed.grab()
    assert not pm.isNull()
