import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from client.diagnose import diagnose_output


def test_python_runtime_error():
    out = ('$ python example.py\nTraceback (most recent call last):\n'
           '  File "/tmp/invariantsmith_run_x/main.py", line 20, in <module>\n    main()\n'
           '  File "/tmp/invariantsmith_run_x/main.py", line 13, in get_user\n    return bar\n'
           "NameError: name 'bar' is not defined\n")
    d = diagnose_output("python", out)
    assert d["line"] == 13 and d["error_type"] == "NameError" and "bar" in d["message"]


def test_python_syntax_error_and_windows_path():
    out = ('  File "C:\\Users\\a\\Temp\\invariantsmith_run_9\\main.py", line 18\n'
           "    print('Database full!\n          ^\nSyntaxError: unterminated string literal (detected at line 18)\n")
    d = diagnose_output("python", out)
    assert d["line"] == 18 and d["error_type"] == "SyntaxError"


def test_python_error_only_in_library_is_ignored():
    out = 'Traceback:\n  File "/usr/lib/python3/json/__init__.py", line 5, in x\nValueError: boom\n'
    assert diagnose_output("python", out) is None


def test_gcc_and_javac():
    g = diagnose_output("c", "/tmp/r/main.c:7:5: error: 'x' undeclared (first use in this function)\n")
    assert g["line"] == 7 and "undeclared" in g["message"]
    j = diagnose_output("java", "/tmp/r/Main.java:4: error: ';' expected\n    int x = 1\n")
    assert j["line"] == 4 and j["message"] == "';' expected"


def test_java_exception_stack():
    out = ('Exception in thread "main" java.lang.ArithmeticException: / by zero\n'
           '\tat Main.div(Main.java:9)\n\tat Main.main(Main.java:5)\n')
    d = diagnose_output("java", out)
    assert d["line"] == 9 and d["error_type"] == "ArithmeticException"


def test_clean_output_gives_none():
    assert diagnose_output("python", "hello\n[Exited with code 0]") is None
