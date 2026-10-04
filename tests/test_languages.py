import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import languages, error_detector


PY_SNIPPET = "def foo():\n    return bar\n"
C_SNIPPET = "#include <stdio.h>\nint main(void) {\n    printf(\"hi\");\n    return 0;\n}\n"
JAVA_SNIPPET = (
    "public class Main {\n"
    "    public static void main(String[] args) {\n"
    "        System.out.println(\"hi\");\n"
    "    }\n"
    "}\n"
)


def test_detect_by_filename_extension_wins_over_content():
    # deliberately Python-looking content, but a .java filename -- the
    # filename should win per resolve_language's documented contract.
    assert languages.detect_language(PY_SNIPPET, "Weird.java") == "java"


def test_detect_python_by_content():
    assert languages.detect_language(PY_SNIPPET) == "python"


def test_detect_c_by_content():
    assert languages.detect_language(C_SNIPPET) == "c"


def test_detect_java_by_content():
    assert languages.detect_language(JAVA_SNIPPET) == "java"


def test_detect_empty_buffer_defaults_to_python():
    assert languages.detect_language("") == "python"


def test_detect_extensionless_filename_falls_through_to_content():
    # Regression test: the client used to send filename="buffer.py" for
    # every fresh/pasted buffer regardless of actual language, which made
    # detect_language trust the .py extension outright and never look at
    # the content -- C or Java pasted into a never-saved buffer got
    # silently misdetected as Python. The client now sends an
    # extensionless "Untitled" sentinel for that case instead (see
    # client/main_window.py), which must fall through to content
    # heuristics exactly like any other unrecognized/missing extension.
    c_code = (
        "#include <stdio.h>\n\n"
        "int factorial(int n) {\n"
        "    if (n == 0 || n == 1) {\n"
        "        return 1;\n"
        "    } else {\n"
        "        return n * factorial(n - 1);\n"
        "    }\n"
        "}\n\n"
        "int main() {\n"
        "    int num;\n"
        "    scanf(\"%d\", &num);\n"
        "    printf(\"Factorial of %d = %d\\n\", num, factorial(num));\n"
        "    return 0;\n"
        "}\n"
    )
    assert languages.detect_language(c_code, "Untitled") == "c"
    assert languages.detect_language(c_code, None) == "c"
    # The bug, preserved as an explicit assertion so nobody "fixes" the
    # extension-priority contract itself by mistake: a .py filename must
    # still win outright per detect_language's documented behavior. The
    # actual fix was the CLIENT no longer sending that filename for a
    # buffer it doesn't know the language of -- not a change here.
    assert languages.detect_language(c_code, "buffer.py") == "python"


def test_resolve_language_explicit_overrides_detection():
    # explicit "c" should win even though the content looks like Python
    assert languages.resolve_language("c", PY_SNIPPET) == "c"


def test_resolve_language_auto_falls_through_to_detection():
    assert languages.resolve_language("auto", JAVA_SNIPPET) == "java"
    assert languages.resolve_language(None, JAVA_SNIPPET) == "java"


def test_analyze_dispatches_by_detected_language():
    py_errors = error_detector.analyze(PY_SNIPPET, "buffer.py")
    assert py_errors and py_errors[0].error_type == "NameError"

    # C/Java analysis differs depending on whether gcc/javac are on PATH
    # (compiler-backed) or not (heuristic fallback) -- either way, this
    # well-formed snippet should report no errors.
    c_errors = error_detector.analyze(C_SNIPPET, "buffer.c")
    assert c_errors == []

    java_errors = error_detector.analyze(JAVA_SNIPPET, "Main.java")
    assert java_errors == []


def test_c_unbalanced_braces_detected_even_without_gcc():
    broken = "int main() {\n    return 0;\n"  # missing closing brace
    errors = error_detector._heuristic_c(broken)
    assert any(e.severity == "syntax" for e in errors)


def test_java_unbalanced_braces_detected_even_without_javac():
    broken = "public class Main {\n    public static void main(String[] a) {\n"
    errors = error_detector._heuristic_java(broken)
    assert any(e.severity == "syntax" for e in errors)


def test_c_missing_main_flagged_by_heuristic():
    no_main = "#include <stdio.h>\nvoid helper() {\n    printf(\"hi\");\n}\n"
    errors = error_detector._heuristic_c(no_main)
    assert any("main()" in e.message for e in errors)


def test_java_missing_entry_point_flagged_by_heuristic():
    no_main = "public class Main {\n    void helper() {\n    }\n}\n"
    errors = error_detector._heuristic_java(no_main)
    assert any("main" in e.message.lower() for e in errors)
