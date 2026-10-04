"""Regression test for the classic C beginner typo `scanf("%d", %n)` instead
of `scanf("%d", &n)`. Reported from a real session: the local model's fix for
the real error was fine, but a *regenerated* fix additionally hallucinated an
unrelated 'main(void)' rewrite, and once one of the two fixes landed, the
other's diff no longer matched the buffer -- every later Apply attempt on it
failed with a 409 ("stale_diff"). This typo is unambiguous once a scanf-family
call is located, so it's handled deterministically instead of going through
the model at all. See server/fixer.py::repair_scanf_address_of.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import error_detector
from server.fixer import repair_scanf_address_of, _try_scanf_address_of_typo


ORIGINAL = (
    '#include <stdio.h>\n'
    'int main() {\n'
    '    int n;\n'
    '    scanf("%d", %n);\n'
    '    printf("%d\\n", n);\n'
    '}\n'
)


def test_reproduces_the_reported_gcc_error():
    errs = error_detector.analyze(ORIGINAL, "Untitled.c", "c")
    syntax_err = next((e for e in errs if e.severity == "syntax"), None)
    assert syntax_err is not None
    assert "expected expression before" in syntax_err.message


def test_repair_fixes_only_the_bad_argument():
    fixed = repair_scanf_address_of(ORIGINAL)
    assert fixed == ORIGINAL.replace('scanf("%d", %n)', 'scanf("%d", &n)')


def test_repair_is_a_noop_on_already_correct_code():
    code = '#include <stdio.h>\nint main(){int n; scanf("%d", &n);}'
    assert repair_scanf_address_of(code) == code


def test_real_percent_n_format_specifier_is_left_alone():
    """%n as an actual format specifier (counts chars written so far) is rare
    but legal C -- it must never be rewritten just because it starts with %."""
    code = (
        '#include <stdio.h>\n'
        'int main() {\n'
        '    int a, b, n;\n'
        '    scanf("%d %d%n", &a, &b, &n);\n'
        '}\n'
    )
    assert repair_scanf_address_of(code) == code


def test_handles_multiple_bad_arguments_in_one_call():
    code = 'void f(){int a,b; scanf("%d %d", %a, %b);}'
    assert repair_scanf_address_of(code) == 'void f(){int a,b; scanf("%d %d", &a, &b);}'


def test_end_to_end_suggest_fix_is_deterministic_and_verified():
    errs = error_detector.analyze(ORIGINAL, "Untitled.c", "c")
    err = next(e for e in errs if e.severity == "syntax")
    result = _try_scanf_address_of_typo(
        ORIGINAL, err.error_type, err.message, "Untitled.c", "c", err.line,
    )
    assert result is not None, "deterministic repair should handle this file"
    assert result.verified is True
    assert result.confidence > 0
    assert "+    scanf(\"%d\", &n);" in result.diff
    assert "main(void)" not in result.diff  # no unrelated, hallucinated changes
