"""Problems list: every error/warning from the last /analyze pass. This is
now just the list (the bottom panel supplies the header, tabs and counts).
Clicking a row jumps the editor there and requests a fix, exactly like
clicking the squiggle."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QStackedWidget, QVBoxLayout, QWidget

from . import icons


class ProblemsPanel(QWidget):
    problemActivated = Signal(dict)

    def __init__(self):
        super().__init__()
        self._errors: list[dict] = []
        self.theme = None
        self.tokens = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("problemList")
        self.list_widget.itemActivated.connect(self._on_item)
        self.list_widget.itemClicked.connect(self._on_item)
        self.empty = QLabel("No problems detected in this file.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.list_widget)
        lay.addWidget(self.stack)

    def counts(self) -> tuple[int, int]:
        err = sum(1 for e in self._errors if e.get("severity") == "syntax")
        return err, len(self._errors) - err

    def set_errors(self, errors: list[dict]):
        self._errors = errors
        self.list_widget.clear()
        self.stack.setCurrentIndex(1 if errors else 0)
        for err in errors:
            syntax = err.get("severity") == "syntax"
            item = QListWidgetItem(f"Ln {err.get('line', '?')}   {err.get('message', '')}")
            item.setData(Qt.ItemDataRole.UserRole, err)
            item.setToolTip(f"{err.get('error_type', '')}: {err.get('message', '')}\nClick for an AI fix")
            if self.tokens is not None:
                item.setIcon(icons.icon("x-circle" if syntax else "alert",
                                        self.tokens.hex(self.tokens.error if syntax else self.tokens.warning), 15))
            self.list_widget.addItem(item)

    def _on_item(self, item):
        err = item.data(Qt.ItemDataRole.UserRole)
        if err:
            self.problemActivated.emit(err)

    def set_theme(self, theme):
        from . import design
        self.theme = theme
        self.tokens = t = design.Tokens(theme)
        self.empty.setStyleSheet(f"color: {t.hex(t.text_faint)}; background: transparent; font-size: 12px;")
        self.list_widget.setStyleSheet(
            f"QListWidget {{ background: {t.hex(t.base)}; border: none; }}" + theme.scrollbar_css())
        self.set_errors(self._errors)
