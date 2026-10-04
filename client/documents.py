"""One open file (or untitled buffer): its text document, highlighter and
per-file editor state. The editor swaps between these on tab change, so undo
history, caret, scroll position and the last analysis result all survive a
tab switch."""
import itertools

from PySide6.QtGui import QTextDocument, QAbstractTextDocumentLayout  # noqa: F401
from PySide6.QtWidgets import QPlainTextDocumentLayout

_ids = itertools.count(1)


class Document:
    def __init__(self, text: str = "", path: str | None = None, name: str = "Untitled",
                 mode: str = "auto", language: str = "python"):
        self.id = next(_ids)
        self.doc = QTextDocument()
        self.doc.setDocumentLayout(QPlainTextDocumentLayout(self.doc))
        self.doc.setPlainText(text)
        self.doc.setModified(False)
        self.path = path            # filesystem path or None if unsaved
        self.name = name            # tab title / logical name sent to the server
        self.mode = mode            # "auto" | "python" | "c" | "java"
        self.language = language    # concrete language driving highlighting/analysis
        self.errors: list[dict] = []
        self.cursor_pos = 0
        self.scroll = 0
        self.highlighter = None

    @property
    def modified(self) -> bool:
        return self.doc.isModified()
