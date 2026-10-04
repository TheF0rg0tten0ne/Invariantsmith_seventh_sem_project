"""Regression test for the classic C beginner typo `if (x = y)` instead of
`if (x == y)`. Reported from a real session: the local model correctly
diagnosed the bug (gcc's own -Wparentheses message says exactly what's
wrong) but its 'fixed_code' was byte-for-byte identical to the broken
input -- it returned high confidence on a complete no-op. This typo is
unambiguous once the condition is a single flat assignment, so it's handled
deterministically instead of going through the model at all. See
server/fixer.py::repair_assignment_in_condition.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import error_detector
from server.fixer import repair_assignment_in_condition, _try_assignment_in_condition_typo


ORIGINAL = (
    '#include <stddef.h>\n'
    'void initialize_database(int *db)\n'
    '{\n'
    '    if (db = NULL)\n'
    '    {\n'
    '        return;\n'
    '    }\n'
    '}\n'
)


def test_reproduces_the_reported_gcc_warning():
    errs = error_detector.analyze(ORIGINAL, "Untitled.c", "c")
    warn = next((e for e in errs if "assignment used as truth value" in e.message), None)
    assert warn is not None


def test_repair_fixes_the_assignment():
    fixed = repair_assignment_in_condition(ORIGINAL)
    assert fixed == ORIGINAL.replace("if (db = NULL)", "if (db == NULL)")


def test_repair_is_a_noop_on_already_correct_code():
    code = "void f(int *db){ if (db == NULL) { return; } }"
    assert repair_assignment_in_condition(code) == code


def test_repair_leaves_already_parenthesized_assignment_alone():
    """Extra parens are how a deliberate assignment-as-condition is written
    without triggering the warning in the first place -- must not touch it."""
    code = "void f(int *db){ if ((db = NULL)) { return; } }"
    assert repair_assignment_in_condition(code) == code


def test_repair_leaves_compound_assignment_alone():
    code = "void f(int n){ while (n += 1) { } }"
    assert repair_assignment_in_condition(code) == code


def test_repair_leaves_relational_operators_alone():
    code = "void f(int n){ if (n <= 0) { return; } if (n >= 10) { return; } }"
    assert repair_assignment_in_condition(code) == code


def test_repair_leaves_compound_boolean_condition_alone():
    """The assignment isn't the WHOLE condition here -- rewriting '=' to
    '==' could silently break a deliberate `if (result = f() && g())`."""
    code = "void f(int a,int b){ int r; if (r = a && b) { } }"
    assert repair_assignment_in_condition(code) == code


def test_repair_leaves_chained_assignment_alone():
    code = "void f(int a,int b,int c){ if (a = b = c) { } }"
    assert repair_assignment_in_condition(code) == code


def test_repair_leaves_for_loop_init_clause_alone():
    code = "void f(void){ for (int i = 0; i < 10; i++) { } }"
    assert repair_assignment_in_condition(code) == code


def test_repair_handles_member_and_pointer_lvalues():
    code = "void f(struct S *s, int *p){ if (s->ready = 0) {} if (*p = 0) {} }"
    assert repair_assignment_in_condition(code) == (
        "void f(struct S *s, int *p){ if (s->ready == 0) {} if (*p == 0) {} }"
    )


def test_repair_handles_while_as_well_as_if():
    code = "void f(int n){ while (n = 0) { } }"
    assert repair_assignment_in_condition(code) == "void f(int n){ while (n == 0) { } }"


def test_end_to_end_suggest_fix_is_deterministic_and_verified():
    errs = error_detector.analyze(ORIGINAL, "Untitled.c", "c")
    warn = next(e for e in errs if "assignment used as truth value" in e.message)
    result = _try_assignment_in_condition_typo(
        ORIGINAL, warn.error_type, warn.message, "Untitled.c", "c", warn.line,
    )
    assert result is not None, "deterministic repair should handle this file"
    assert result.verified is True
    assert result.confidence > 0
    assert "+    if (db == NULL)" in result.diff


def test_end_to_end_suggest_fix_does_not_touch_the_compound_case():
    """When the condition isn't flat, the deterministic layer must step
    aside rather than produce a wrong or unverifiable 'fix'."""
    code = "int pick(int a,int b){ int r; if (r = a && b) { return r; } return 0; }"
    errs = error_detector.analyze(code, "Untitled.c", "c")
    warn = next((e for e in errs if "assignment used as truth value" in e.message), None)
    if warn is None:
        return  # this compiler/version didn't flag it -- nothing to assert
    result = _try_assignment_in_condition_typo(
        code, warn.error_type, warn.message, "Untitled.c", "c", warn.line,
    )
    assert result is None
