"""Turn a failed run's output (Python traceback, gcc error, javac error or
Java exception) into the same error dict /analyze produces, so the Fix
Insight panel can ask the model for a fix for something that only showed up
at runtime. Pure functions; no Qt."""
import re

_PY_FILE = re.compile(r'File "([^"]*)", line (\d+)')
_PY_EXC = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Warning|Interrupt)?)(?::\s*(.*))?$")
_GCC = re.compile(r"^(?P<file>[^\s:][^:]*\.[ch]):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?:fatal )?error:\s*(?P<msg>.+)$")
_JAVAC = re.compile(r"^(?P<file>[^\s:][^:]*\.java):(?P<line>\d+):\s*error:\s*(?P<msg>.+)$")
_JEXC = re.compile(r"^Exception in thread \"[^\"]*\"\s+([\w.$]+)(?::\s*(.*))?$")
_JAT = re.compile(r"\bat [\w.$<>]+\((?P<file>[\w.]+\.java):(?P<line>\d+)\)")


def _is_user_file(path: str, names: tuple) -> bool:
    base = re.split(r"[\\/]", path)[-1]
    return base in names


def diagnose_output(language: str, text: str, user_names: tuple = ("main.py", "main.c", "Main.java")) -> dict | None:
    """Best-effort. Returns {line, error_type, message, severity, source} or None.
    `user_names` are the temp file names the runner used for the user's code."""
    lines = [l.rstrip("\r") for l in text.splitlines()]
    if language == "python":
        last_line = None
        for l in lines:
            m = _PY_FILE.search(l)
            if m and _is_user_file(m.group(1), user_names):
                last_line = int(m.group(2))
        if last_line is None:
            return None
        for l in reversed(lines):
            if l.startswith(("[", "$")) or not l.strip() or l.startswith((" ", "\t")):
                continue
            m = _PY_EXC.match(l.strip())
            if m and ("Error" in m.group(1) or "Exception" in m.group(1) or m.group(1).endswith(("Exit", "Interrupt"))):
                return {"line": last_line, "error_type": m.group(1).split(".")[-1],
                        "message": (m.group(2) or m.group(1)).strip(), "severity": "syntax", "source": "run"}
        return None
    if language == "c":
        for l in lines:
            m = _GCC.match(l)
            if m and _is_user_file(m.group("file"), user_names):
                return {"line": int(m.group("line")), "error_type": "CompileError",
                        "message": m.group("msg").strip(), "severity": "syntax", "source": "run"}
        return None
    if language == "java":
        for l in lines:
            m = _JAVAC.match(l)
            if m and _is_user_file(m.group("file"), user_names + tuple(
                    re.split(r"[\\/]", m.group("file"))[-1:])):
                return {"line": int(m.group("line")), "error_type": "CompileError",
                        "message": m.group("msg").strip(), "severity": "syntax", "source": "run"}
        for i, l in enumerate(lines):
            m = _JEXC.match(l)
            if m:
                for follow in lines[i + 1:i + 12]:
                    a = _JAT.search(follow)
                    if a:
                        return {"line": int(a.group("line")), "error_type": m.group(1).split(".")[-1],
                                "message": (m.group(2) or m.group(1)).strip(), "severity": "syntax",
                                "source": "run"}
        return None
    return None
