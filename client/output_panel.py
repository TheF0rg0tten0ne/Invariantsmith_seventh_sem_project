"""Console widgets for the bottom panel.

ConsoleView  - read-only monospace log that appends text and auto-scrolls
               (only while the user is already at the bottom, so scrolling
               up to read earlier output isn't yanked back down).
TerminalView - a ConsoleView plus a one-line stdin field. stdin is captured
               when a run starts (the runner pipes it in at launch); pressing
               Enter in the field re-runs with the new input.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from . import design


class ConsoleView(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setObjectName("console")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setMaximumBlockCount(5000)      # bound memory on chatty programs
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)

    def append_output(self, text: str):
        vs = self.verticalScrollBar()
        at_bottom = vs.value() >= vs.maximum() - 4
        cur = self.textCursor()
        sel = cur.hasSelection()
        end = QTextCursor(self.document())
        end.movePosition(QTextCursor.MoveOperation.End)
        end.insertText(text)
        if at_bottom and not sel:
            vs.setValue(vs.maximum())

    def set_theme(self, theme):
        t = design.Tokens(theme)
        self.setFont(design.mono_font(10.0))
        self.setStyleSheet(f"QPlainTextEdit#console {{ background: {t.hex(t.base)}; color: {t.hex(t.text)}; "
                           f"border: none; padding: 8px 12px; }}" + theme.scrollbar_css())


class TerminalView(QWidget):
    stdinSubmitted = Signal(str)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.console = ConsoleView()
        lay.addWidget(self.console, stretch=1)
        row = QWidget()
        row.setObjectName("stdinRow")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 5, 12, 6)
        rl.setSpacing(8)
        self.prompt = QLabel("stdin")
        self.prompt.setObjectName("infoItem")
        self.stdin_field = QLineEdit()
        self.stdin_field.setPlaceholderText("Program input, sent when the run starts. Press Enter to re-run with it.")
        self.stdin_field.returnPressed.connect(lambda: self.stdinSubmitted.emit(self.stdin_field.text()))
        rl.addWidget(self.prompt)
        rl.addWidget(self.stdin_field, stretch=1)
        lay.addWidget(row)

    def stdin_text(self) -> str:
        text = self.stdin_field.text()
        return (text + "\n") if text and not text.endswith("\n") else text

    def append_output(self, text: str):
        self.console.append_output(text)

    def clear(self):
        self.console.clear()

    def set_theme(self, theme):
        self.console.set_theme(theme)
