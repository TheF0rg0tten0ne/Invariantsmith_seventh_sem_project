"""
Client-side mirror of server/languages.py's id/label/extension table.

Kept tiny and duplicated (rather than imported across the process
boundary -- client and server are separate processes/venvs by design)
so the toolbar's language picker and the editor's file-open dialog have
something to show immediately, before any round trip to the server. The
server remains the source of truth for detection and analysis; this is
just display metadata plus an "auto" sentinel the client uses to mean
"let the server figure it out."
"""
from dataclasses import dataclass

AUTO = "auto"


@dataclass(frozen=True)
class LanguageProfile:
    id: str
    label: str
    extensions: tuple
    default_filename: str


PYTHON = LanguageProfile("python", "Python", (".py",), "buffer.py")
C = LanguageProfile("c", "C", (".c", ".h"), "buffer.c")
JAVA = LanguageProfile("java", "Java", (".java",), "Main.java")

LANGUAGES = {p.id: p for p in (PYTHON, C, JAVA)}
LANGUAGE_ORDER = [PYTHON.id, C.id, JAVA.id]

_EXTENSION_MAP = {ext: p.id for p in LANGUAGES.values() for ext in p.extensions}


def language_for_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    lowered = filename.lower()
    for ext in sorted(_EXTENSION_MAP, key=len, reverse=True):
        if lowered.endswith(ext):
            return _EXTENSION_MAP[ext]
    return None


def default_extension(language_id: str) -> str:
    profile = LANGUAGES.get(language_id)
    return profile.extensions[0] if profile else ".py"


def file_filter_string() -> str:
    """For QFileDialog: one 'All supported' entry plus one per language."""
    all_exts = " ".join(f"*{ext}" for p in LANGUAGES.values() for ext in p.extensions)
    parts = [f"All supported ({all_exts})"]
    for lid in LANGUAGE_ORDER:
        p = LANGUAGES[lid]
        exts = " ".join(f"*{ext}" for ext in p.extensions)
        parts.append(f"{p.label} ({exts})")
    parts.append("All files (*)")
    return ";;".join(parts)
