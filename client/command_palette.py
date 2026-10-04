"""Ctrl+Shift+P command palette: every action in the app, searchable by
typing a few letters of it (subsequence match), with its shortcut shown."""
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget, QLabel


def _score(query: str, text: str) -> int | None:
    """Subsequence match. Lower is better; None = no match."""
    q, t = query.lower(), text.lower()
    if not q:
        return 0
    if q in t:
        return t.index(q)
    i = 0
    gaps = 0
    last = -1
    for ch in q:
        j = t.find(ch, i)
        if j < 0:
            return None
        gaps += (j - last - 1) if last >= 0 else j
        last = j
        i = j + 1
    return 100 + gaps


class CommandPalette(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("palette")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.commands: list[tuple[str, str, callable]] = []
        self._active: list[tuple[str, str, callable]] = []
        self._keep_order = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 6)
        v.setSpacing(0)
        self.input = QLineEdit()
        self.input.setObjectName("paletteInput")
        self.input.setPlaceholderText("Type a command\u2026")
        self.input.textChanged.connect(self._filter)
        self.input.installEventFilter(self)
        v.addWidget(self.input)
        self.list = QListWidget()
        self.list.setObjectName("paletteList")
        self.list.itemActivated.connect(self._run)
        self.list.itemClicked.connect(self._run)
        v.addWidget(self.list)
        self.hint = QLabel("No matching command")
        self.hint.setObjectName("muted")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setVisible(False)
        v.addWidget(self.hint)
        self.setVisible(False)

    def set_commands(self, commands: list[tuple[str, str, callable]]):
        self.commands = commands

    def open(self, commands=None, placeholder: str = "Type a command\u2026", keep_order: bool = False):
        """Open the palette. With ``commands`` it becomes a picker over that
        list instead (Go to File, Go to Symbol); ``keep_order`` keeps the
        list's own order until the user types something."""
        self._active = commands if commands is not None else self.commands
        self._keep_order = keep_order
        self.input.setPlaceholderText(placeholder)
        self.reposition()
        self.input.clear()
        self._filter("")
        self.show()
        self.raise_()
        self.adjustSize()
        self.input.setFocus()

    def reposition(self):
        w = min(560, max(360, self.parent().width() - 80))
        self.setFixedWidth(w)
        self.list.setFixedHeight(300)
        self.move((self.parent().width() - w) // 2, 70)

    def close_palette(self):
        self.hide()

    def _filter(self, text: str):
        self.list.clear()
        scored = []
        for i, (title, shortcut, fn) in enumerate(self._active):
            s = _score(text.strip(), title)
            if s is not None:
                scored.append((s, i if self._keep_order else title, title, shortcut, fn))
        scored.sort(key=lambda x: (x[0], x[1]))
        for _, _, title, shortcut, fn in scored:
            it = QListWidgetItem(f"{title}" + (f"        {shortcut}" if shortcut else ""))
            it.setData(Qt.ItemDataRole.UserRole, fn)
            it.setData(Qt.ItemDataRole.UserRole + 1, title)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.setVisible(bool(self.list.count()))
        self.hint.setVisible(not self.list.count())

    def _run(self, item):
        fn = item.data(Qt.ItemDataRole.UserRole)
        self.close_palette()
        if fn:
            fn()

    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == QEvent.Type.KeyPress:
            k = ev.key()
            if k == Qt.Key.Key_Escape:
                self.close_palette()
                return True
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if k == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                it = self.list.currentItem()
                if it:
                    self._run(it)
                return True
        return super().eventFilter(obj, ev)
