"""
Language definitions + auto-detection heuristics.

Kept dependency-free (no external language-ID library, no network) so
this works fully offline -- consistent with the rest of Invariantsmith's
"no network calls, ever" design. Detection only has to pick among the
three supported grammars, not identify an arbitrary language, so a small
weighted-pattern scorer is plenty; it doesn't need to be a real parser.
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LanguageProfile:
    id: str                 # canonical id used everywhere: "python" | "c" | "java"
    label: str               # display name for the UI
    extensions: tuple        # file extensions this language claims; first is canonical
    fence: str                # markdown code-fence tag used in model prompts
    comment_prefix: str       # single-line comment token
    default_filename: str     # sensible default buffer name for this language


PYTHON = LanguageProfile("python", "Python", (".py",), "python", "#", "buffer.py")
C = LanguageProfile("c", "C", (".c", ".h"), "c", "//", "buffer.c")
JAVA = LanguageProfile("java", "Java", (".java",), "java", "//", "Main.java")

LANGUAGES: dict[str, LanguageProfile] = {p.id: p for p in (PYTHON, C, JAVA)}
LANGUAGE_ORDER = [PYTHON.id, C.id, JAVA.id]

_EXTENSION_MAP = {ext: p.id for p in LANGUAGES.values() for ext in p.extensions}


def language_for_filename(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    lowered = filename.lower()
    # Longest-extension-first so ".h" doesn't win over some hypothetical
    # longer suffix; not load-bearing today with only single-dot
    # extensions, but cheap insurance if more languages are added later.
    for ext in sorted(_EXTENSION_MAP, key=len, reverse=True):
        if lowered.endswith(ext):
            return _EXTENSION_MAP[ext]
    return None


# --- content heuristics ---------------------------------------------------
# Weighted regex signals. Each hit contributes its weight to that
# language's score; the language with the highest total wins. Weights are
# hand-tuned so a single strong, unambiguous marker (an #include, a
# `public static void main`) dominates a pile of weak/ambiguous ones.

_JAVA_SIGNS = [
    (re.compile(r"\bpublic\s+class\s+\w+"), 4),
    (re.compile(r"\bpublic\s+static\s+void\s+main\s*\("), 6),
    (re.compile(r"\bSystem\.out\.print(ln)?\s*\("), 3),
    (re.compile(r"^\s*import\s+java\.", re.MULTILINE), 4),
    # NOTE: previously there was also a generic `public (static)? (final)?
    # (void|int|...)` pattern here at weight 2. It's been removed: it
    # matches the exact same text as the `public static void main(`
    # pattern above on any real Java entry point, so it was silently
    # double-counting a single line's signal rather than adding a new
    # one -- which let a small embedded Java snippet (e.g. pasted inside
    # an otherwise-C or otherwise-Python buffer) outscore much stronger,
    # whole-file structural signals from the actual source language.
    (re.compile(r"\bnew\s+[A-Z]\w*\s*\("), 1),
    (re.compile(r"@Override\b"), 3),
]

_C_SIGNS = [
    (re.compile(r"^\s*#\s*include\s*[<\"]"), 6),
    (re.compile(r"\bprintf\s*\("), 3),
    (re.compile(r"\bscanf\s*\("), 3),
    (re.compile(r"\bint\s+main\s*\(\s*(void|int\s+argc)?"), 4),
    (re.compile(r"^\s*#\s*define\b", re.MULTILINE), 3),
    (re.compile(r"\bstruct\s+\w+\s*\{"), 2),
    (re.compile(r"->\s*\w+"), 1),
    (re.compile(r"\bmalloc\s*\(|\bfree\s*\("), 2),
]

_PY_SIGNS = [
    (re.compile(r"^\s*def\s+\w+\s*\(.*\)\s*:", re.MULTILINE), 4),
    (re.compile(r"^\s*import\s+\w+\s*$", re.MULTILINE), 2),
    (re.compile(r"^\s*from\s+\w+(\.\w+)*\s+import\b", re.MULTILINE), 3),
    (re.compile(r"\bprint\s*\("), 2),
    (re.compile(r"^\s*class\s+\w+.*:\s*$", re.MULTILINE), 3),
    (re.compile(r"\bself\b"), 2),
    (re.compile(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']\s*:", re.MULTILINE), 5),
    (re.compile(r"\belif\b"), 2),
]


def _score(code: str, signs) -> int:
    return sum(weight for pattern, weight in signs if pattern.search(code))


# A leading preprocessor directive -- #include / #define / #pragma, with
# only whitespace and // or /* */ comments allowed before it -- is a
# near-certain structural signal that the WHOLE file is C, not just a
# file that happens to score a few C-flavored points. Real-world C files
# essentially always open this way, and nothing else in these three
# supported grammars produces a leading '#directive' line. This is
# checked before the weighted scorer so that content appearing LATER in
# the buffer (a pasted snippet of another language, a comment block
# containing other-language-looking text, etc.) can never outvote it --
# matching the "a single strong, unambiguous marker dominates a pile of
# weak/ambiguous ones" intent below, which pure summed-weight scoring
# doesn't actually guarantee on its own.
_LEADING_C_DIRECTIVE = re.compile(
    r"\A(?:\s*(?://[^\n]*\n|/\*.*?\*/))*\s*#\s*(include|define|pragma)\b",
    re.DOTALL,
)


def detect_language(code: str, filename: Optional[str] = None) -> str:
    """Best-effort language id for a code buffer.

    Filename extension wins outright when it's one we recognize -- a
    ".java" file that happens to contain confusing snippets shouldn't get
    second-guessed. Content heuristics only decide when the extension is
    missing/unknown (a fresh unsaved buffer, a paste, a plain ".txt").
    """
    by_ext = language_for_filename(filename)
    if by_ext:
        return by_ext

    if not code or not code.strip():
        return PYTHON.id

    if _LEADING_C_DIRECTIVE.match(code):
        return C.id

    scores = {
        JAVA.id: _score(code, _JAVA_SIGNS),
        C.id: _score(code, _C_SIGNS),
        PYTHON.id: _score(code, _PY_SIGNS),
    }
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return PYTHON.id
    return best


def resolve_language(requested: Optional[str], code: str, filename: Optional[str] = None) -> str:
    """Turn a client-supplied language hint into a concrete, known id.

    'auto' / None / anything unrecognized -> detect_language(). An
    explicit, known id is trusted and passed through unchanged -- if the
    user manually picked "C" from the dropdown, that overrides whatever
    the heuristics would have guessed.
    """
    if requested and requested in LANGUAGES:
        return requested
    return detect_language(code, filename)


def list_profiles() -> list[dict]:
    return [
        {
            "id": LANGUAGES[lid].id,
            "label": LANGUAGES[lid].label,
            "extensions": list(LANGUAGES[lid].extensions),
        }
        for lid in LANGUAGE_ORDER
    ]
