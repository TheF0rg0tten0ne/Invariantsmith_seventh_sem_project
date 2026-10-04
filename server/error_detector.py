"""
Fast static analysis pass, now multi-language.

Runs on every debounced keystroke via /analyze. Python keeps the original
cheap ast.parse + pyflakes pipeline. C and Java prefer shelling out to the
system's real compiler in syntax-only mode (gcc / javac) when one is on
PATH -- that's a genuine parser, far better than anything hand-rolled
here, and it's still a purely local, offline call, consistent with the
rest of this project. When no compiler is available, we fall back to a
deliberately modest heuristic pass (brace/paren balance + a handful of
high-confidence structural checks) rather than pretending to have real
C/Java parsing.
"""
import ast
import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from pyflakes.api import check
from pyflakes.reporter import Reporter

from . import languages


@dataclass
class CodeError:
    line: int
    col: int
    error_type: str
    message: str
    severity: str  # 'syntax' | 'lint' | 'warning'

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------
# Python (unchanged behavior -- ast + pyflakes)
# ---------------------------------------------------------------------

def check_syntax(code: str) -> Optional[CodeError]:
    """Fastest possible check: does it even parse as Python?"""
    try:
        ast.parse(code)
        return None
    except SyntaxError as e:
        return CodeError(
            line=e.lineno or 0,
            col=e.offset or 0,
            error_type="SyntaxError",
            message=str(e.msg),
            severity="syntax",
        )


def check_lint(code: str, filename: str = "<buffer>") -> list[CodeError]:
    """pyflakes pass: undefined names, unused imports, etc."""
    out, err = io.StringIO(), io.StringIO()
    reporter = Reporter(out, err)
    check(code, filename, reporter)

    errors = []
    for line in out.getvalue().splitlines():
        # pyflakes format: "<filename>:<line>:<col>: <message>"
        parts = line.split(":", 3)
        if len(parts) >= 4:
            try:
                line_no = int(parts[1])
                col_no = int(parts[2])
            except ValueError:
                continue
            message = parts[3].strip()
            errors.append(CodeError(
                line=line_no,
                col=col_no,
                error_type=_classify_message(message),
                message=message,
                severity="lint",
            ))
    return errors


def _classify_message(message: str) -> str:
    lowered = message.lower()
    if "undefined name" in lowered:
        return "NameError"
    if "imported but unused" in lowered:
        return "UnusedImport"
    if "redefinition" in lowered:
        return "Redefinition"
    if "local variable" in lowered and ("unused" in lowered or "never used" in lowered):
        return "UnusedVariable"
    return "LintWarning"


def _analyze_python(code: str, filename: str = "<buffer>") -> list[CodeError]:
    syntax_error = check_syntax(code)
    if syntax_error:
        return [syntax_error]
    return check_lint(code, filename)


# ---------------------------------------------------------------------
# C -- gcc -fsyntax-only when available, else a heuristic pass
# ---------------------------------------------------------------------

_GCC_LINE_RE = re.compile(r"^<stdin>:(\d+):(\d+):\s*(error|warning|note):\s*(.+)$")


def _run_gcc(code: str) -> Optional[list[CodeError]]:
    if shutil.which("gcc") is None:
        return None
    try:
        proc = subprocess.run(
            ["gcc", "-fsyntax-only", "-Wall", "-Wextra", "-x", "c", "-"],
            input=code, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    errors: list[CodeError] = []
    for raw_line in proc.stderr.splitlines():
        m = _GCC_LINE_RE.match(raw_line.strip())
        if not m:
            continue
        line_no, col_no, kind, message = m.groups()
        if kind == "note":
            continue
        errors.append(CodeError(
            line=int(line_no), col=int(col_no),
            error_type="SyntaxError" if kind == "error" else "LintWarning",
            message=message,
            severity="syntax" if kind == "error" else "warning",
        ))
    return errors


def _check_balance(code: str, open_ch: str, close_ch: str, label: str) -> Optional[CodeError]:
    """Line/col of the first unmatched delimiter, or of the opening one if
    something opened but never closed. Skips '//' comments, '/* */'
    comments, and string/char literal contents in the crudest way -- good
    enough to dodge the most common false positive (a brace character
    inside a string literal) without a real tokenizer."""
    depth = 0
    line, col = 1, 1
    in_string: Optional[str] = None
    i, n = 0, len(code)
    open_stack: list[tuple[int, int]] = []
    while i < n:
        c = code[i]
        if in_string:
            if c == "\\":
                i += 2
                col += 2
                continue
            if c == in_string:
                in_string = None
        elif c in ("'", '"'):
            in_string = c
        elif c == "/" and i + 1 < n and code[i + 1] == "/":
            nl = code.find("\n", i)
            if nl == -1:
                break
            col += nl - i
            i = nl
            continue
        elif c == "/" and i + 1 < n and code[i + 1] == "*":
            end = code.find("*/", i + 2)
            if end == -1:
                break
            segment = code[i:end + 2]
            line += segment.count("\n")
            i = end + 2
            col = 1  # approximate; block comments rarely need exact col
            continue
        elif c == open_ch:
            depth += 1
            open_stack.append((line, col))
        elif c == close_ch:
            depth -= 1
            if depth < 0:
                return CodeError(line=line, col=col, error_type="SyntaxError",
                                  message=f"Unmatched closing '{close_ch}' ({label}).",
                                  severity="syntax")
            open_stack.pop()

        if c == "\n":
            line += 1
            col = 1
        else:
            col += 1
        i += 1

    if depth > 0:
        oline, ocol = open_stack[0]
        return CodeError(line=oline, col=ocol, error_type="SyntaxError",
                          message=f"Unmatched opening '{open_ch}' ({label}) -- never closed.",
                          severity="syntax")
    return None


def _heuristic_c(code: str) -> list[CodeError]:
    errors = []
    for open_ch, close_ch, label in (("{", "}", "braces"), ("(", ")", "parentheses")):
        err = _check_balance(code, open_ch, close_ch, label)
        if err:
            errors.append(err)
    if errors:
        # An unbalanced structure makes everything downstream unreliable --
        # same short-circuit philosophy as the Python syntax-first pass.
        return errors

    if not re.search(r"\bint\s+main\s*\(|void\s+main\s*\(", code):
        errors.append(CodeError(
            line=1, col=1, error_type="LintWarning",
            message="No main() function found -- this file won't produce a runnable program on its own.",
            severity="warning",
        ))
    if re.search(r"\bprintf\s*\(", code) and not re.search(r'#\s*include\s*[<"]stdio\.h[">]', code):
        errors.append(CodeError(
            line=1, col=1, error_type="LintWarning",
            message="printf() is used but <stdio.h> is not included.",
            severity="warning",
        ))
    if re.search(r"\bmalloc\s*\(|\bfree\s*\(", code) and not re.search(r'#\s*include\s*[<"]stdlib\.h[">]', code):
        errors.append(CodeError(
            line=1, col=1, error_type="LintWarning",
            message="malloc()/free() is used but <stdlib.h> is not included.",
            severity="warning",
        ))
    return errors


def _analyze_c(code: str, filename: str = "<buffer>") -> list[CodeError]:
    gcc_result = _run_gcc(code)
    if gcc_result is not None:
        return gcc_result
    return _heuristic_c(code)


# ---------------------------------------------------------------------
# Java -- javac when available, else a heuristic pass
# ---------------------------------------------------------------------

_JAVAC_LINE_RE = re.compile(r"^(.+\.java):(\d+):\s*(error|warning):\s*(.+)$")


def _run_javac(code: str) -> Optional[list[CodeError]]:
    if shutil.which("javac") is None:
        return None
    class_match = re.search(r"\bpublic\s+(?:final\s+|abstract\s+)?class\s+(\w+)", code)
    class_name = class_match.group(1) if class_match else "Main"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src_path = Path(tmp) / f"{class_name}.java"
            src_path.write_text(code, encoding="utf-8")
            proc = subprocess.run(
                ["javac", "-d", tmp, "-Xlint:all", str(src_path)],
                capture_output=True, text=True, timeout=15,
            )
    except (OSError, subprocess.TimeoutExpired):
        return None

    errors: list[CodeError] = []
    for raw_line in proc.stderr.splitlines():
        m = _JAVAC_LINE_RE.match(raw_line.strip())
        if not m:
            continue
        _, line_no, kind, message = m.groups()
        errors.append(CodeError(
            line=int(line_no), col=1,
            error_type="SyntaxError" if kind == "error" else "LintWarning",
            message=message,
            severity="syntax" if kind == "error" else "warning",
        ))
    return errors


def _heuristic_java(code: str) -> list[CodeError]:
    errors = []
    for open_ch, close_ch, label in (("{", "}", "braces"), ("(", ")", "parentheses")):
        err = _check_balance(code, open_ch, close_ch, label)
        if err:
            errors.append(err)
    if errors:
        return errors

    if not re.search(r"\bclass\s+\w+", code):
        errors.append(CodeError(
            line=1, col=1, error_type="LintWarning",
            message="No class declaration found -- every Java file needs at least one class.",
            severity="warning",
        ))
    if re.search(r"\bpublic\s+class\s+(\w+)", code) and not re.search(r"\bpublic\s+static\s+void\s+main\s*\(", code):
        errors.append(CodeError(
            line=1, col=1, error_type="LintWarning",
            message="No 'public static void main(String[] args)' entry point found.",
            severity="warning",
        ))
    return errors


_JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;", re.MULTILINE)


def _find_unused_imports_java(code: str) -> list[CodeError]:
    """javac -- unlike pyflakes -- never flags unused imports, under any
    -Xlint category. Without this, UnusedImport (Python's single largest
    training-data class, ~19% of it) would simply be unreachable for
    Java. Regex/text-match rather than real symbol resolution, same
    spirit as the rest of this module's "cheap heuristics, not a real
    parser" design: check whether the imported simple name appears
    anywhere else in the file. Wildcard imports (`import java.util.*;`)
    are skipped -- can't tell usage without actually resolving symbols.
    """
    errors = []
    for m in _JAVA_IMPORT_RE.finditer(code):
        full = m.group(1)
        if full.endswith(".*"):
            continue
        simple_name = full.rsplit(".", 1)[-1]
        rest = code[:m.start()] + code[m.end():]
        if not re.search(rf"\b{re.escape(simple_name)}\b", rest):
            line = code.count("\n", 0, m.start()) + 1
            errors.append(CodeError(
                line=line, col=1, error_type="UnusedImport",
                message=f"'{full}' is never used.",
                severity="warning",
            ))
    return errors


def _analyze_java(code: str, filename: str = "<buffer>") -> list[CodeError]:
    javac_result = _run_javac(code)
    errors = list(javac_result) if javac_result is not None else _heuristic_java(code)
    # Only layer the unused-import scan on top of a file that's otherwise
    # syntactically sound -- same short-circuit philosophy as the balance
    # check above: don't bother reasoning about imports in a file that
    # doesn't even compile/parse.
    if not any(e.severity == "syntax" for e in errors):
        errors += _find_unused_imports_java(code)
    return errors


# ---------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------

def analyze(code: str, filename: str = "<buffer>", language: Optional[str] = None) -> list[CodeError]:
    """Full static pass, dispatched by language.

    `language` follows the same contract as the rest of the API: None or
    "auto" triggers detection (filename extension first, content
    heuristics otherwise); an explicit "python"/"c"/"java" is trusted.
    """
    lang = languages.resolve_language(language, code, filename)
    if lang == languages.C.id:
        return _analyze_c(code, filename)
    if lang == languages.JAVA.id:
        return _analyze_java(code, filename)
    return _analyze_python(code, filename)
