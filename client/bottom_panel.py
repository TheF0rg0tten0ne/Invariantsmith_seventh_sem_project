"""
Bottom dock: PROBLEMS | OUTPUT | TERMINAL.

Why this replaces the old stacked Problems + Output panels: each used a
height-animated body inside a vertical splitter. When "minimised" the body's
maximumHeight and the splitter's remembered size disagreed, and the panel
kept demanding more space than the window had, which is what pushed it off
the screen and scrunched the editor. Here there is exactly one dock with:

  * a fixed 36px header that is always visible,
  * a body that is simply shown or hidden (no animation to get stuck),
  * a height that is always clamped to what the window can actually spare
    (see MainWindow._fit_bottom), and
  * a maximise toggle that grows the dock to most of the editor column
    instead of fighting the splitter.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from . import icons
from .output_panel import ConsoleView, TerminalView
from .problems_panel import ProblemsPanel
from .widgets import IconButton

HEADER_H = 36
MIN_BODY_H = 90


class BottomPanel(QWidget):
    tabChanged = Signal(str)
    closeRequested = Signal()
    maximizeToggled = Signal(bool)

    TABS = (("problems", "PROBLEMS"), ("output", "OUTPUT"), ("terminal", "TERMINAL"))

    def __init__(self):
        super().__init__()
        self.setObjectName("bottomPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.tokens = None
        self.maximized = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QWidget()
        header.setObjectName("bottomHeader")
        header.setFixedHeight(HEADER_H)
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.setSpacing(0)
        self.tab_buttons: dict[str, QPushButton] = {}
        self.badges: dict[str, QLabel] = {}
        for key, label in self.TABS:
            b = QPushButton(label)
            b.setObjectName("bottomTab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, k=key: self.show_tab(k))
            self.tab_buttons[key] = b
            hl.addWidget(b)
            if key == "problems":
                badge = QLabel("")
                badge.setObjectName("countPill")
                badge.setVisible(False)
                self.badges[key] = badge
                hl.addWidget(badge)
                hl.addSpacing(4)
        hl.addStretch()
        self.clear_btn = IconButton("trash", "Clear output", 26, 15)
        self.max_btn = IconButton("chevron-up", "Maximise panel", 26, 15)
        self.close_btn = IconButton("x", "Hide panel (Ctrl+J)", 26, 15)
        self.clear_btn.clicked.connect(self.clear_current)
        self.max_btn.clicked.connect(self.toggle_maximize)
        self.close_btn.clicked.connect(self.closeRequested)
        for w in (self.clear_btn, self.max_btn, self.close_btn):
            hl.addWidget(w)
        lay.addWidget(header)

        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(MIN_BODY_H)
        self.problems = ProblemsPanel()
        self.output = ConsoleView()
        self.terminal = TerminalView()
        self.stack.addWidget(self.problems)
        self.stack.addWidget(self.output)
        self.stack.addWidget(self.terminal)
        lay.addWidget(self.stack, stretch=1)
        self.setMinimumHeight(HEADER_H + MIN_BODY_H)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._current = "problems"
        self.show_tab("problems", emit=False)

    def show_tab(self, key: str, emit: bool = True):
        self._current = key
        for k, b in self.tab_buttons.items():
            b.setChecked(k == key)
        self.stack.setCurrentIndex([k for k, _ in self.TABS].index(key))
        self.clear_btn.setVisible(key != "problems")
        if emit:
            self.tabChanged.emit(key)

    def current_tab(self) -> str:
        return self._current

    def clear_current(self):
        if self._current == "output":
            self.output.clear()
        elif self._current == "terminal":
            self.terminal.clear()

    def set_problem_counts(self, errors: int, warnings: int):
        b = self.badges["problems"]
        total = errors + warnings
        b.setVisible(total > 0)
        b.setText(str(total))
        b.setObjectName("countPillErr" if errors else "countPill")
        b.style().unpolish(b)
        b.style().polish(b)

    def toggle_maximize(self):
        self.maximized = not self.maximized
        self.max_btn.set_icon_name("chevron-down" if self.maximized else "chevron-up")
        self.max_btn.setToolTip("Restore panel size" if self.maximized else "Maximise panel")
        self.maximizeToggled.emit(self.maximized)

    def retheme(self, theme, tokens):
        self.tokens = tokens
        for b in (self.clear_btn, self.max_btn, self.close_btn):
            b.retheme(tokens)
        self.problems.set_theme(theme)
        self.output.set_theme(theme)
        self.terminal.set_theme(theme)
