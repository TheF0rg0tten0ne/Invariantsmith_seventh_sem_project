"""Keyboard shortcut cheat sheet (Help > Keyboard Shortcuts, or the palette)."""
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

_SECTIONS = [
    ("Writing code", [
        ("Ctrl+Space", "Open suggestions (they also pop up as you type)"),
        ("Tab / Enter", "Accept the highlighted suggestion"),
        ("Tab / Shift+Tab", "Next / previous snippet placeholder"),
        ("Esc", "Close suggestions / leave the snippet"),
        ("( [ { \" '", "Auto-close; type the closer to step over it; select text first to wrap it"),
        ("Enter between { }", "Opens the block with the closer on its own line"),
        ("Ctrl+/", "Toggle comment"),
        ("Tab / Shift+Tab", "Indent / outdent the selection"),
        ("Ctrl+] / Ctrl+[", "Indent / outdent the line"),
    ]),
    ("Lines", [
        ("Shift+Enter", "New line below, keeping the indent"),
        ("Ctrl+Shift+Enter", "New line above"),
        ("Ctrl+Shift+K", "Delete line"),
        ("Ctrl+Shift+D", "Duplicate line"),
        ("Alt+Up / Alt+Down", "Move line up / down"),
        ("Ctrl+L", "Select line (press again to extend)"),
        ("Ctrl+C / Ctrl+X", "With nothing selected: copy / cut the whole line"),
        ("Home", "Jump to first character, then column 0"),
        ("Ctrl+D", "Select the word, then its next occurrence"),
        ("Ctrl+Shift+\\", "Jump to the matching bracket"),
    ]),
    ("Go to", [
        ("Ctrl+P", "Go to file in the open folder"),
        ("Ctrl+Shift+O", "Go to function / class in this file"),
        ("Ctrl+G", "Go to line"),
        ("Ctrl+Shift+P", "Command palette"),
        ("Ctrl+F / Ctrl+H", "Find / replace"),
        ("Ctrl+Tab", "Next tab"),
    ]),
    ("Run & AI", [
        ("F5 / F6 / Shift+F5", "Run / Debug with AI diagnosis / Stop"),
        ("Ctrl+.", "Fix next problem"),
        ("Ctrl+Enter", "Accept the suggested fix"),
        ("Alt+Enter", "Accept and go to the next fix"),
        ("Ctrl+Shift+A", "Re-analyse the file"),
    ]),
    ("View", [
        ("Ctrl+B / Ctrl+J / Ctrl+Alt+B", "Toggle sidebar / panel / Fix Insight"),
        ("Ctrl+Wheel, Ctrl++ / Ctrl+-", "Zoom the editor (Ctrl+0 resets)"),
        ("Alt+Z", "Toggle word wrap"),
    ]),
]


def shortcuts_html(tokens) -> str:
    fg, muted = tokens.hex(tokens.text), tokens.hex(tokens.text_muted)
    acc, line = tokens.hex(tokens.accent), tokens.hex(tokens.hairline)
    chip = tokens.hex(tokens.raised)
    out = [f"<body style='color:{fg};'>"]
    for title, rows in _SECTIONS:
        out.append(f"<h3 style='color:{acc}; margin:14px 0 4px 0;'>{title}</h3>"
                   f"<table width='100%' cellspacing='0' cellpadding='5'>")
        for k, desc in rows:
            k = k.replace("&", "&amp;").replace("<", "&lt;")
            out.append(f"<tr><td width='38%' style='border-bottom:1px solid {line};'>"
                       f"<span style='background:{chip}; font-family:monospace;'>&nbsp;{k}&nbsp;</span></td>"
                       f"<td style='border-bottom:1px solid {line}; color:{muted};'>{desc}</td></tr>")
        out.append("</table>")
    out.append("</body>")
    return "".join(out)


class ShortcutsDialog(QDialog):
    def __init__(self, tokens, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(640, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        self.view = QTextBrowser()
        self.view.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.view.setHtml(shortcuts_html(tokens))
        v.addWidget(self.view)
        row = QHBoxLayout()
        row.addStretch()
        done = QPushButton("Close")
        done.setObjectName("accentBtn")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)
