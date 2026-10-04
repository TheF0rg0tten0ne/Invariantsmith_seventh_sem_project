"""Regression tests for the C repairs added after the 954-line sample
(tests/fixtures/sample_buggy.c) kept falling through to the small LLM:

  * printf("%f", <int>) -- fixed at the root cause (int division), not by a cast
  * gets(buf)           -- bounded fgets + newline strip
  * _verify_fix         -- must count OCCURRENCES of a diagnostic: two lines with
                           byte-identical gcc messages made every correct fix of
                           one of them look like a no-op.

The end-to-end test disables the model entirely: every diagnostic in the
sample must be fixable without it.
"""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import error_detector, fixer
from server.diff_utils import apply_diff

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_buggy.c").read_text()
needs_gcc = pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc not installed")

AVG = (
    '#include <stdio.h>\n'
    'int avg(int *v, int n)\n{\n    int t = 0;\n    for (int i = 0; i < n; i++) t += v[i];\n'
    '    return t / n;\n}\n'
    'int main(void)\n{\n    int v[3] = {1, 2, 4};\n    int a = avg(v, 3);\n'
    '    printf("%.2f\\n", a);\n    return 0;\n}\n'
)


def test_printf_float_with_int_widens_function_and_variable():
    fixed = fixer.repair_printf_int_for_float(AVG)
    assert "double avg(" in fixed
    assert "return (double)t / n;" in fixed
    assert "double a = avg(v, 3);" in fixed


def test_printf_float_with_unrelated_int_is_left_alone_without_a_diagnostic():
    code = '#include <stdio.h>\nint main(void){ int x = 3; printf("%f\\n", x); return 0; }\n'
    assert fixer.repair_printf_int_for_float(code) == code  # no evidence of lost precision


def test_printf_float_cast_fallback_hits_only_the_named_argument():
    code = '#include <stdio.h>\nint main(void)\n{\n    int x = 3;\n    printf("%d %f\\n", x, x);\n    return 0;\n}\n'
    msg = "format \u2018%f\u2019 expects argument of type \u2018double\u2019, but argument 3 has type \u2018int\u2019 [-Wformat=]"
    fixed = fixer.repair_printf_int_for_float(code, line=5, message=msg)
    assert 'printf("%d %f\\n", x, (double)x);' in fixed


def test_gets_becomes_bounded_fgets_and_adds_string_h():
    code = '#include <stdio.h>\nint main(void)\n{\n    char b[16];\n    gets(b);\n    return 0;\n}\n'
    fixed = fixer.repair_gets(code)
    assert "fgets(b, sizeof(b), stdin)" in fixed
    assert "#include <string.h>" in fixed
    assert "gets(b);" not in fixed.replace("fgets(b", "")


def test_gets_on_a_char_pointer_is_not_guessed_at():
    code = '#include <stdio.h>\nvoid f(char *p)\n{\n    gets(p);\n}\n'
    assert fixer.repair_gets(code) == code


@needs_gcc
def test_verify_counts_occurrences_of_identical_diagnostics():
    msg = "format \u2018%f\u2019 expects argument of type \u2018double\u2019, but argument 2 has type \u2018int\u2019 [-Wformat=]"
    two = ('#include <stdio.h>\nint main(void)\n{\n    int a = 1;\n'
           '    printf("%f\\n", a);\n    printf("%f\\n", a);\n    return 0;\n}\n')
    one_fixed = two.replace('printf("%f\\n", a);\n    printf', 'printf("%f\\n", (double)a);\n    printf', 1)
    _, verified, _ = fixer._verify_fix(two, one_fixed, "LintWarning", msg, "t.c", "c")
    assert verified is True


@needs_gcc
@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_every_diagnostic_in_the_sample_is_fixed_without_the_model(monkeypatch, eol):
    def no_model():
        raise AssertionError("the LLM must not be needed for any diagnostic in the sample")
    monkeypatch.setattr(fixer, "_get_model", no_model)

    code = SAMPLE.replace("\n", eol)
    for _ in range(12):
        errs = error_detector.analyze(code, "sample.c", "c")
        if not errs:
            break
        e = errs[0]
        r = fixer.suggest_fix(code, e.error_type, e.message, "sample.c", "c", e.line)
        assert r.verified, f"line {e.line}: {e.message} -> {r.rationale}"
        code = apply_diff(code, r.diff)
    assert error_detector.analyze(code, "sample.c", "c") == []
    assert "double calculate_average_age" in code


# --- integer length modifiers (platform-dependent: MinGW/Windows flags these, Linux doesn't) ---
PTRDIFF_MSG = ("format \u2018%ld\u2019 expects argument of type \u2018long int\u2019, "
               "but argument 2 has type \u2018long long int\u2019 [-Wformat=]")
PTR_CODE = ('#include <stdio.h>\n#include <string.h>\nint main(void)\n{\n    char first[16] = "Hello World";\n'
            '    char *ptr = strstr(first, "World");\n    if (ptr)\n    {\n'
            '        printf("Found at: %ld\\n", ptr - first);\n    }\n    return 0;\n}\n')


def test_pointer_difference_uses_td():
    fixed = fixer.repair_printf_int_length(PTR_CODE, 9, PTRDIFF_MSG)
    assert 'printf("Found at: %td\\n", ptr - first);' in fixed


def test_pointer_difference_repair_survives_crlf_and_goes_through_suggest_fix(monkeypatch):
    monkeypatch.setattr(fixer, "_get_model", lambda: (_ for _ in ()).throw(AssertionError("no LLM")))
    code = PTR_CODE.replace("\n", "\r\n")
    r = fixer.suggest_fix(code, "LintWarning", PTRDIFF_MSG, "t.c", "c", 9)
    assert r.verified and "%td" in apply_diff(code, r.diff)


def test_sizeof_uses_zu_and_plain_long_long_uses_lld():
    code = ('#include <stdio.h>\nint main(void)\n{\n    long long big = 5;\n'
            '    printf("%d %ld\\n", 1, big);\n    printf("%d\\n", sizeof(int));\n    return 0;\n}\n')
    m = ("format \u2018%ld\u2019 expects argument of type \u2018long int\u2019, "
         "but argument 3 has type \u2018long long int\u2019 [-Wformat=]")
    assert 'printf("%d %lld\\n", 1, big);' in fixer.repair_printf_int_length(code, 5, m)
    m = ("format \u2018%d\u2019 expects argument of type \u2018int\u2019, "
         "but argument 2 has type \u2018long long unsigned int\u2019 [-Wformat=]")
    assert 'printf("%zu\\n", sizeof(int));' in fixer.repair_printf_int_length(code, 6, m)
