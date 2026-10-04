"""
Main window -- the three-column layout from the design mockup:

    +-- title bar: logo | brand | document tabs | Run Debug Stop | layout theme bell gear | _ [] x --+
    | rail | sidebar          | breadcrumb                       | FIX INSIGHT                       |
    |      | (explorer,       | editor + minimap                 | issue, rationale, diff,           |
    |      |  outline,        | info strip                       | Accept / Reject / Apply & Next,   |
    |      |  timeline)       | PROBLEMS | OUTPUT | TERMINAL     | checks & verification             |
    +-- status bar: errors warnings runtime ............ Offline Mode  AI Model: ... --------------+

Layout rules that keep panels from getting scrunched or running off-screen
(the bugs this rewrite fixes):
  * One horizontal splitter (sidebar | centre | fix panel) and one vertical
    splitter (editor | bottom dock). Neither lets a pane be crushed below its
    minimum, and every panel's size is clamped to what the window can
    actually spare (see _fit_layout) whenever the window or a panel changes.
  * The window has a real minimum size, and a saved geometry is validated
    against the current screen before it's restored.
  * The bottom dock has a permanent header and a body that is simply shown
    or hidden -- no height animation to get stuck half-way.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThreadPool, QRunnable, QObject, Signal, QEvent, QByteArray, QPoint
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QGuiApplication, QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QMainWindow, QMenu, QMessageBox, QSplitter, QVBoxLayout,
    QHBoxLayout, QWidget,
)

from . import config, design, icons
from . import languages as client_languages
from .api_client import InvariantsmithClient
from .bottom_panel import BottomPanel, HEADER_H, MIN_BODY_H
from .chrome import FramelessResizer, StatusBar, TitleBar, STATUS_H
from .command_palette import CommandPalette
from .convert_dialog import ConvertDialog
from .diagnose import diagnose_output
from .editor_area import EditorArea
from .editor_widget import CodeEditor
from .executor import CodeRunner
from .prefs import Prefs
from .settings_dialog import SettingsDialog
from .shortcuts_dialog import ShortcutsDialog
from .sidebar import ActivityBar, SideBar
from .suggestion_panel import SuggestionPanel
from .theme import Theme
from .theme_picker import ThemeButton, ThemePopup
from .widgets import ToastManager

MIN_WIN_W, MIN_WIN_H = 1120, 640
# Cheap "does this code read from stdin" signal per language, used only to
# warn when the Terminal's stdin field is empty before a run (see _run_code):
# scanf()/input()/Scanner(System.in) reading nothing (immediate EOF) is a
# silent failure -- e.g. an uninitialized C variable then prints whatever
# garbage was already on the stack, with no error at all.
_STDIN_READ_PATTERNS = {
    "python": re.compile(r"\binput\s*\("),
    "c": re.compile(r"\b(scanf|fscanf|getchar|getc)\s*\(|\bfgets\s*\([^;]*\bstdin\b"),
    "java": re.compile(r"\bnew\s+Scanner\s*\(\s*System\s*\.\s*in\s*\)|\bSystem\s*\.\s*in\b"),
}

MIN_CENTER_W = 420
MIN_EDITOR_H = 200
SIDEBAR_RANGE = (200, 420)
RIGHT_RANGE = (380, 560)

SAMPLE_CODE = (
    'import json\nfrom typing import List\n\n'
    'def load_users(path: str) -> List[dict]:\n'
    '    with open(path, "r", encoding="utf-8") as f:\n'
    '        data = json.load(f)\n'
    '        return data["users"]\n\n'
    'def get_user(names: List[dict], username: str) -> dict:\n'
    '    for u in names:\n'
    '        if u["username"] == username:\n'
    '            return u\n'
    '    return bar\n\n'
    'def main():\n'
    '    users = load_users("users.json")\n'
    '    user = get_user(users, "alice")\n'
    '    print(user["email"])\n\n'
    'if __name__ == "__main__":\n'
    '    main()\n'
)

_FALLBACK_THEME = {
    "name": "invariant_gold", "label": "Invariantsmith Gold",
    "colors": {
        "background": "#14151a", "foreground": "#d8dae2", "gutter": "#1b1d24", "selection": "#3a3220",
        "cursor": "#e6c378", "keyword": "#c9a0e8", "string": "#e3a35e", "number": "#b7d49a", "comment": "#5f6472",
        "function": "#e8d27a", "class": "#6fd0c4", "variable": "#8fc6e8", "operator": "#d8dae2",
        "error-underline": "#e5484d", "warning-underline": "#e6c378", "ai-suggestion-bg": "#2c2514",
        "ai-suggestion-text": "#e0b454", "ai-ghost-text": "#6b6f7d", "diff-add-bg": "#16301f",
        "diff-add-text": "#7fd99a", "diff-remove-bg": "#34191a", "diff-remove-text": "#e88a8a"},
}


# ---------------------------------------------------------------------------
class _StatusSignals(QObject):
    finished = Signal(dict)
    failed = Signal()


class _ModelStatusWorker(QRunnable):
    """model_status() is a network call; polling it must never touch the GUI thread."""

    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.signals = _StatusSignals()

    def run(self):
        try:
            self.signals.finished.emit(self.api_client.model_status())
        except Exception:
            self.signals.failed.emit()


def _load_themes_from_disk() -> list[dict]:
    out = []
    folder = Path(__file__).resolve().parent.parent / "themes"
    for f in sorted(folder.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def _fit_to_screen(win: QMainWindow, w: int, h: int):
    scr = QGuiApplication.primaryScreen()
    avail = scr.availableGeometry() if scr else None
    if avail is not None:
        w, h = min(w, avail.width() - 40), min(h, avail.height() - 40)
    win.resize(max(w, 600), max(h, 420))
    if avail is not None:
        win.move(avail.x() + (avail.width() - win.width()) // 2, avail.y() + (avail.height() - win.height()) // 2)


# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.prefs = Prefs()
        self.native_frame = bool(self.prefs.get("native_frame")) or os.environ.get("INVARIANTSMITH_NATIVE_FRAME") == "1"
        self.setWindowTitle("InvariantSmith")
        self.setAcceptDrops(True)
        if not self.native_frame:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        scr = QGuiApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else None
        self.setMinimumSize(min(MIN_WIN_W, avail.width() - 20) if avail else MIN_WIN_W,
                            min(MIN_WIN_H, avail.height() - 20) if avail else MIN_WIN_H)

        self.api_client = InvariantsmithClient()
        self.themes: dict[str, Theme] = {}
        self.theme_labels: dict[str, str] = {}
        self.current_theme: Theme | None = None
        self.tokens: design.Tokens | None = None
        self._pool = QThreadPool.globalInstance()
        self._untitled_n = 0
        self._pending_next = False
        self._run_buffer = ""
        self._run_language = "python"
        self._run_name = "Untitled"
        self._run_debug = False
        self._server_state = "checking"
        self._model_state = "idle"
        self._last_run_error: dict | None = None
        self._preview_name: str | None = None
        self._theme_before: Theme | None = None
        self._bottom_user_h = int(self.prefs.get("bottom_height"))

        self._build_ui()
        self.toasts = ToastManager(self)
        self.toasts.bottom_margin = STATUS_H + 14
        self._build_actions()
        self._load_themes()
        self._restore_session()

        self.runner = CodeRunner(self)
        self.runner.outputReady.connect(self._on_run_output)
        self.runner.finished.connect(self._on_run_finished)
        self.runner.failedToStart.connect(self._on_run_failed_to_start)

        self._poll_timer = QTimer(self)
        self._poll_timer.setSingleShot(True)
        self._poll_timer.timeout.connect(self._poll_model_status)
        self._poll_model_status()

        self.resizer = FramelessResizer(self)
        self.resizer.enabled = not self.native_frame
        QApplication.instance().installEventFilter(self.resizer)

    # ==================================================================
    # UI construction
    # ==================================================================
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(self, self.native_frame)
        root.addWidget(self.title_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.activity = ActivityBar()
        body.addWidget(self.activity)

        self.editor = CodeEditor(self.api_client)
        self.editor_area = EditorArea(self.editor)
        self.bottom = BottomPanel()
        self.sidebar = SideBar(self.api_client)
        self.fix_panel = SuggestionPanel(self.api_client)
        self.suggestion_panel = self.fix_panel   # (older name, kept for callers)

        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.setChildrenCollapsible(False)
        self.v_split.setHandleWidth(5)
        self.v_split.addWidget(self.editor_area)
        self.v_split.addWidget(self.bottom)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setStretchFactor(1, 0)
        self.editor_area.setMinimumHeight(MIN_EDITOR_H)

        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.setChildrenCollapsible(False)
        self.h_split.setHandleWidth(5)
        self.h_split.addWidget(self.sidebar)
        self.h_split.addWidget(self.v_split)
        self.h_split.addWidget(self.fix_panel)
        self.h_split.setStretchFactor(0, 0)
        self.h_split.setStretchFactor(1, 1)
        self.h_split.setStretchFactor(2, 0)
        self.sidebar.setMinimumWidth(SIDEBAR_RANGE[0])
        self.sidebar.setMaximumWidth(SIDEBAR_RANGE[1])
        self.fix_panel.setMinimumWidth(RIGHT_RANGE[0])
        self.fix_panel.setMaximumWidth(RIGHT_RANGE[1])
        self.v_split.setMinimumWidth(MIN_CENTER_W)
        body.addWidget(self.h_split, stretch=1)
        root.addLayout(body, stretch=1)

        self.status = StatusBar()
        root.addWidget(self.status)

        self.palette = CommandPalette(self)
        self.theme_btn = ThemeButton()
        self.theme_btn.clickedPicker.connect(self._open_theme_picker)
        self.title_bar.theme_slot.addWidget(self.theme_btn)

        # ---- wiring --------------------------------------------------
        tb = self.title_bar
        tb.tabbar.tabSelected.connect(self._select_tab_by_id)
        tb.tabbar.tabCloseRequested.connect(self._close_tab_by_id)
        tb.tabbar.newTabRequested.connect(self._new_file)
        tb.runClicked.connect(lambda: self._run_code(False))
        tb.debugClicked.connect(lambda: self._run_code(True))
        tb.stopClicked.connect(self._stop_code)
        tb.toggleSidebar.connect(self._toggle_sidebar)
        tb.toggleBottom.connect(self._toggle_bottom)
        tb.toggleRight.connect(self._toggle_right)
        tb.settingsClicked.connect(self._open_settings)
        tb.notificationsClicked.connect(self._show_notifications)

        self.activity.pageSelected.connect(self._show_sidebar_page)
        self.activity.toggleCollapse.connect(self._toggle_sidebar)
        self.activity.terminalClicked.connect(self._toggle_bottom)
        self.activity.settingsClicked.connect(self._open_settings)

        sb = self.sidebar
        sb.openFile.connect(self._open_path)
        sb.openFolderRequested.connect(self._open_folder_dialog)
        sb.gotoLine.connect(lambda ln, col: self.editor.goto_line(ln, col or None))
        sb.openResult.connect(lambda p, ln: self._open_path(p, ln))
        sb.runRequested.connect(lambda: self._run_code(False))
        sb.debugRequested.connect(lambda: self._run_code(True))
        sb.stopRequested.connect(self._stop_code)
        sb.convertRequested.connect(self._convert_to)
        self.title_bar.convertRequested.connect(self._convert_to)

        self.bottom.closeRequested.connect(self._toggle_bottom)
        self.bottom.maximizeToggled.connect(self._on_bottom_maximize)
        self.bottom.problems.problemActivated.connect(self._on_problem_activated)
        self.bottom.terminal.stdinSubmitted.connect(self._on_stdin_submitted)

        fp = self.fix_panel
        fp.fixAccepted.connect(self._on_fix_accepted)
        fp.closeRequested.connect(self._toggle_right)
        fp.statusMessage.connect(lambda text, kind: self._toast(text, kind))

        ed = self.editor
        ed.errorsChanged.connect(self._on_errors_changed)
        ed.errorClicked.connect(self._on_error_clicked)
        ed.languageDetected.connect(self._on_language_detected)
        ed.documentSwitched.connect(self._on_document_switched)
        ed.zoomChanged.connect(self._on_zoom)
        ed.textChanged.connect(self._schedule_outline)

        self.status.problemsClicked.connect(self._show_problems)
        self.status.modelClicked.connect(self._model_clicked)
        self.status.languageClicked.connect(self._language_menu)

        self.h_split.splitterMoved.connect(self._on_h_moved)
        self.v_split.splitterMoved.connect(self._on_v_moved)

        self._outline_timer = QTimer(self)
        self._outline_timer.setSingleShot(True)
        self._outline_timer.setInterval(450)
        self._outline_timer.timeout.connect(self._refresh_outline)
        self._status_msg_timer = QTimer(self)
        self._status_msg_timer.setSingleShot(True)
        self._status_msg_timer.timeout.connect(lambda: self.status.set_message(""))
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(40)
        self._fit_timer.timeout.connect(self._fit_layout)

        # initial visibility / sizes from prefs
        self._sidebar_visible = bool(self.prefs.get("sidebar_visible"))
        self._bottom_visible = bool(self.prefs.get("bottom_visible"))
        self._right_visible = bool(self.prefs.get("right_visible"))
        self._sidebar_page = self.prefs.get("sidebar_page") or "explorer"
        if self._sidebar_page not in self.sidebar.page_index:
            self._sidebar_page = "explorer"
        self.sidebar.show_page(self._sidebar_page)
        tab = self.prefs.get("bottom_tab")
        self.bottom.show_tab(tab if tab in ("problems", "output", "terminal") else "problems", emit=False)
        self.editor.apply_settings(font_size=self.prefs.get("font_size"), tab_width=self.prefs.get("tab_width"),
                                   word_wrap=self.prefs.get("word_wrap"), auto_close=self.prefs.get("auto_close"),
                                   suggestions=self.prefs.get("suggestions"),
                                   indent_guides=self.prefs.get("indent_guides"))
        self.editor_area.set_tab_width(self.editor.tab_width)
        self.editor_area.set_minimap_visible(bool(self.prefs.get("minimap")))
        self._apply_visibility()

    # ------------------------------------------------------------------
    # Actions, shortcuts, menus
    # ------------------------------------------------------------------
    def _act(self, text, slot, shortcut=None) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        a.triggered.connect(lambda _=False, s=slot: s())
        self.addAction(a)        # keeps the shortcut live even when the menu isn't open
        return a

    def _build_actions(self):
        S = QKeySequence.StandardKey
        a = {}
        a["new"] = self._act("New File", self._new_file, S.New)
        a["open"] = self._act("Open File\u2026", self._open_file_dialog, S.Open)
        a["folder"] = self._act("Open Folder\u2026", self._open_folder_dialog, "Ctrl+K")
        a["save"] = self._act("Save", self._save_current, S.Save)
        a["saveas"] = self._act("Save As\u2026", self._save_as_current, S.SaveAs)
        a["close"] = self._act("Close Tab", self._close_current_tab, "Ctrl+W")
        a["quit"] = self._act("Exit", self.close, "Ctrl+Q")
        a["undo"] = self._act("Undo", self.editor.undo, S.Undo)
        a["redo"] = self._act("Redo", self.editor.redo, S.Redo)
        a["find"] = self._act("Find\u2026", lambda: self.editor_area.find_bar.open_bar(False), S.Find)
        a["replace"] = self._act("Replace\u2026", lambda: self.editor_area.find_bar.open_bar(True), "Ctrl+H")
        a["goto"] = self._act("Go to Line\u2026", self._goto_line_dialog, "Ctrl+G")
        a["quickopen"] = self._act("Go to File\u2026", self._quick_open, "Ctrl+P")
        a["symbol"] = self._act("Go to Symbol in File\u2026", self._goto_symbol, "Ctrl+Shift+O")
        a["comment"] = self._act("Toggle Comment", self.editor.toggle_comment, "Ctrl+/")
        a["dup"] = self._act("Duplicate Line", self.editor.duplicate_line, "Ctrl+Shift+D")
        a["sidebar"] = self._act("Toggle Sidebar", self._toggle_sidebar, "Ctrl+B")
        a["bottom"] = self._act("Toggle Panel", self._toggle_bottom, "Ctrl+J")
        a["right"] = self._act("Toggle Fix Insight", self._toggle_right, "Ctrl+Alt+B")
        a["explorer"] = self._act("Show Explorer", lambda: self._show_sidebar_page("explorer"), "Ctrl+Shift+E")
        a["search"] = self._act("Search in Folder", lambda: self._show_sidebar_page("search"), "Ctrl+Shift+F")
        a["problems"] = self._act("Show Problems", self._show_problems, "Ctrl+Shift+M")
        a["minimap"] = self._act("Toggle Minimap", self._toggle_minimap)
        a["wrap"] = self._act("Toggle Word Wrap", self._toggle_wrap, "Alt+Z")
        a["zin"] = self._act("Zoom In", lambda: self.editor.zoom(1))
        a["zout"] = self._act("Zoom Out", lambda: self.editor.zoom(-1))
        a["palette"] = self._act("Command Palette\u2026", self.palette.open, "Ctrl+Shift+P")
        a["settings"] = self._act("Settings\u2026", self._open_settings, "Ctrl+,")
        a["next"] = self._act("Fix Next Problem", self._fix_next_problem, "Ctrl+.")
        a["regen"] = self._act("Regenerate Fix", self.fix_panel.regenerate)
        a["analyze"] = self._act("Re-analyze File", self.editor.analyze_now, "Ctrl+Shift+A")
        a["run"] = self._act("Run", lambda: self._run_code(False), "F5")
        a["debug"] = self._act("Debug (Run + AI Diagnose)", lambda: self._run_code(True), "F6")
        a["stop"] = self._act("Stop", self._stop_code, "Shift+F5")
        a["nexttab"] = self._act("Next Tab", lambda: self._cycle_tab(1), "Ctrl+Tab")
        a["prevtab"] = self._act("Previous Tab", lambda: self._cycle_tab(-1), "Ctrl+Shift+Tab")
        self.A = a

        # The Accept / Apply & Next buttons advertise Ctrl+Enter / Alt+Enter; make that real.
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=lambda: self._click_if(self.fix_panel.accept_btn))
        QShortcut(QKeySequence("Alt+Return"), self, activated=lambda: self._click_if(self.fix_panel.next_btn))

        m = QMenu(self)
        fm = m.addMenu("&File")
        for k in ("new", "open", "folder"):
            fm.addAction(a[k])
        self.recent_menu = fm.addMenu("Open Recent")
        fm.addSeparator()
        for k in ("save", "saveas", "close"):
            fm.addAction(a[k])
        fm.addSeparator()
        fm.addAction(a["quit"])
        em = m.addMenu("&Edit")
        for k in ("undo", "redo"):
            em.addAction(a[k])
        em.addSeparator()
        for k in ("find", "replace", "goto", "quickopen", "symbol", "comment", "dup"):
            em.addAction(a[k])
        vm = m.addMenu("&View")
        for k in ("palette", "sidebar", "bottom", "right", "minimap", "wrap", "zin", "zout"):
            vm.addAction(a[k])
        vm.addSeparator()
        for k in ("explorer", "search", "problems"):
            vm.addAction(a[k])
        rm = m.addMenu("&AI")
        for k in ("next", "regen", "analyze"):
            rm.addAction(a[k])
        cm = rm.addMenu("Convert to")
        self._convert_menu_actions = {}
        for lid in client_languages.LANGUAGE_ORDER:
            ca = QAction(client_languages.LANGUAGES[lid].label, self)
            ca.triggered.connect(lambda _=False, t=lid: self._convert_to(t))
            cm.addAction(ca)
            self._convert_menu_actions[lid] = ca
        um = m.addMenu("&Run")
        for k in ("run", "debug", "stop"):
            um.addAction(a[k])
        m.addSeparator()
        m.addAction(a["settings"])
        self._shortcuts_action = QAction("Keyboard Shortcuts\u2026", self)
        self._shortcuts_action.triggered.connect(lambda _=False: self._show_shortcuts())
        m.addAction(self._shortcuts_action)
        self.title_bar.logo.setMenu(m)
        self.main_menu = m
        self._rebuild_recent_menu()

        self.palette.set_commands([
            ("File: New File", "Ctrl+N", self._new_file), ("File: Open File\u2026", "Ctrl+O", self._open_file_dialog),
            ("File: Open Folder\u2026", "Ctrl+K", self._open_folder_dialog), ("File: Save", "Ctrl+S", self._save_current),
            ("File: Save As\u2026", "Ctrl+Shift+S", self._save_as_current), ("File: Close Tab", "Ctrl+W", self._close_current_tab),
            ("Edit: Find", "Ctrl+F", lambda: self.editor_area.find_bar.open_bar(False)),
            ("Edit: Replace", "Ctrl+H", lambda: self.editor_area.find_bar.open_bar(True)),
            ("Edit: Go to Line\u2026", "Ctrl+G", self._goto_line_dialog),
            ("Go to: File\u2026", "Ctrl+P", self._quick_open),
            ("Go to: Symbol in File\u2026", "Ctrl+Shift+O", self._goto_symbol),
            ("Edit: Trigger Suggestions", "Ctrl+Space", lambda: self.editor.show_suggestions(manual=True)),
            ("Edit: Delete Line", "Ctrl+Shift+K", self.editor.delete_line),
            ("Edit: Select Line", "Ctrl+L", self.editor.select_line),
            ("Edit: Insert Line Below", "Shift+Enter", lambda: self.editor.insert_line(False)),
            ("Edit: Insert Line Above", "Ctrl+Shift+Enter", lambda: self.editor.insert_line(True)),
            ("Edit: Select Next Occurrence", "Ctrl+D", self.editor.select_next_occurrence),
            ("Edit: Go to Matching Bracket", "Ctrl+Shift+\\", self.editor.goto_matching_bracket),
            ("Edit: Trim Trailing Whitespace", "", self._tidy_current),
            ("View: Toggle Indent Guides", "", lambda: self._toggle_pref("indent_guides", "Indent guides")),
            ("Preferences: Toggle Auto-Close Brackets", "", lambda: self._toggle_pref("auto_close", "Auto-close")),
            ("Preferences: Toggle Code Suggestions", "", lambda: self._toggle_pref("suggestions", "Code suggestions")),
            ("Help: Keyboard Shortcuts", "", self._show_shortcuts),
            ("Edit: Toggle Comment", "Ctrl+/", self.editor.toggle_comment),
            ("Edit: Duplicate Line", "Ctrl+Shift+D", self.editor.duplicate_line),
            ("View: Toggle Sidebar", "Ctrl+B", self._toggle_sidebar), ("View: Toggle Panel", "Ctrl+J", self._toggle_bottom),
            ("View: Toggle Fix Insight", "Ctrl+Alt+B", self._toggle_right),
            ("View: Toggle Minimap", "", self._toggle_minimap), ("View: Toggle Word Wrap", "Alt+Z", self._toggle_wrap),
            ("View: Show Problems", "Ctrl+Shift+M", self._show_problems),
            ("View: Show Output", "", lambda: self._show_bottom_tab("output")),
            ("View: Show Terminal", "", lambda: self._show_bottom_tab("terminal")),
            ("View: Maximise Panel", "", self.bottom.toggle_maximize),
            ("View: Choose Theme\u2026", "", self._open_theme_picker),
            ("View: Zoom In", "Ctrl++", lambda: self.editor.zoom(1)), ("View: Zoom Out", "Ctrl+-", lambda: self.editor.zoom(-1)),
            ("AI: Fix Next Problem", "Ctrl+.", self._fix_next_problem), ("AI: Regenerate Fix", "", self.fix_panel.regenerate),
            ("AI: Re-analyze File", "Ctrl+Shift+A", self.editor.analyze_now),
            ("AI: Convert to Python", "", lambda: self._convert_to("python")),
            ("AI: Convert to C", "", lambda: self._convert_to("c")),
            ("AI: Convert to Java", "", lambda: self._convert_to("java")),
            ("Run: Run", "F5", lambda: self._run_code(False)), ("Run: Debug (AI diagnose)", "F6", lambda: self._run_code(True)),
            ("Run: Stop", "Shift+F5", self._stop_code),
            ("Language: Auto-detect", "", lambda: self._set_language("auto")),
            ("Language: Python", "", lambda: self._set_language("python")),
            ("Language: C", "", lambda: self._set_language("c")),
            ("Language: Java", "", lambda: self._set_language("java")),
            ("Preferences: Settings", "Ctrl+,", self._open_settings),
        ])

    def _click_if(self, btn):
        if btn.isEnabled() and self._right_visible:
            btn.click()

    # ==================================================================
    # Layout: visibility, sizes, clamping
    # ==================================================================
    def _apply_visibility(self):
        self.sidebar.setVisible(self._sidebar_visible)
        self.bottom.setVisible(self._bottom_visible)
        self.fix_panel.setVisible(self._right_visible)
        tb = self.title_bar
        tb.side_btn.setChecked(self._sidebar_visible)
        tb.bottom_btn.setChecked(self._bottom_visible)
        tb.right_btn.setChecked(self._right_visible)
        self.activity.set_active(self._sidebar_page if self._sidebar_visible else None)
        QTimer.singleShot(0, self._fit_layout)

    def _fit_layout(self, *_):
        """Re-assert panel sizes inside what the window can actually spare."""
        total = self.h_split.width()
        if total > 50:
            sb = max(SIDEBAR_RANGE[0], min(SIDEBAR_RANGE[1], int(self.prefs.get("sidebar_width")))) if self._sidebar_visible else 0
            rt = max(RIGHT_RANGE[0], min(RIGHT_RANGE[1], int(self.prefs.get("right_width")))) if self._right_visible else 0
            over = MIN_CENTER_W - (total - sb - rt)
            if over > 0:                      # not enough room: shrink right first, then sidebar
                take = min(over, max(0, rt - RIGHT_RANGE[0]))
                rt -= take
                over -= take
                if over > 0 and sb:
                    sb = max(SIDEBAR_RANGE[0], sb - over)
            self.h_split.setSizes([sb, max(1, total - sb - rt), rt])
        th = self.v_split.height()
        if th > 50 and self._bottom_visible:
            lo = HEADER_H + MIN_BODY_H
            hi = max(lo, th - MIN_EDITOR_H)
            want = int(th * 0.72) if self.bottom.maximized else self._bottom_user_h
            bh = max(lo, min(hi, want))
            self.v_split.setSizes([th - bh, bh])

    def _on_h_moved(self, *_):
        sizes = self.h_split.sizes()
        if self._sidebar_visible and sizes[0] > 0:
            self.prefs.set("sidebar_width", sizes[0])
        if self._right_visible and sizes[2] > 0:
            self.prefs.set("right_width", sizes[2])

    def _on_v_moved(self, *_):
        sizes = self.v_split.sizes()
        if self._bottom_visible and sizes[1] > 0 and not self.bottom.maximized:
            self._bottom_user_h = sizes[1]
            self.prefs.set("bottom_height", sizes[1])

    def _on_bottom_maximize(self, maxed: bool):
        if not self._bottom_visible:
            self._bottom_visible = True
            self._apply_visibility()
        self._fit_layout()

    def _toggle_sidebar(self):
        self._sidebar_visible = not self._sidebar_visible
        self.prefs.set("sidebar_visible", self._sidebar_visible)
        self._apply_visibility()

    def _toggle_bottom(self):
        self._bottom_visible = not self._bottom_visible
        self.prefs.set("bottom_visible", self._bottom_visible)
        if not self._bottom_visible and self.bottom.maximized:
            self.bottom.toggle_maximize()
        self._apply_visibility()

    def _toggle_right(self):
        self._right_visible = not self._right_visible
        self.prefs.set("right_visible", self._right_visible)
        self._apply_visibility()

    def _show_right(self):
        if not self._right_visible:
            self._right_visible = True
            self.prefs.set("right_visible", True)
            self._apply_visibility()

    def _show_sidebar_page(self, key: str):
        self._sidebar_page = key
        self.prefs.set("sidebar_page", key)
        self.sidebar.show_page(key)
        self._sidebar_visible = True
        self.prefs.set("sidebar_visible", True)
        self._apply_visibility()

    def _show_bottom_tab(self, key: str):
        self.bottom.show_tab(key)
        self.prefs.set("bottom_tab", key)
        if not self._bottom_visible:
            self._bottom_visible = True
            self.prefs.set("bottom_visible", True)
            self._apply_visibility()

    def _show_problems(self):
        self._show_bottom_tab("problems")

    def _toggle_minimap(self):
        v = not bool(self.prefs.get("minimap"))
        self.prefs.set("minimap", v)
        self.editor_area.set_minimap_visible(v)

    def _toggle_wrap(self):
        v = not bool(self.prefs.get("word_wrap"))
        self.prefs.set("word_wrap", v)
        self.editor.apply_settings(word_wrap=v)
        self._toast(f"Word wrap {'on' if v else 'off'}", "info", ms=1500)

    def _on_zoom(self, n: int):
        self.status.set_message(f"Zoom: {n}pt")
        self._status_msg_timer.start(1800)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.title_bar.set_compact(self.width() < 1260)
        if hasattr(self, "toasts"):
            self.toasts.reposition()
        if self.palette.isVisible():
            self.palette.reposition()
        self._fit_timer.start()

    def changeEvent(self, e):
        if e.type() == QEvent.Type.WindowStateChange:
            self.title_bar.sync_max_icon()
            self._fit_timer.start()
        super().changeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._fit_layout)

    # ==================================================================
    # Theming
    # ==================================================================
    def _load_themes(self):
        try:
            theme_dicts = self.api_client.themes()
        except Exception:
            theme_dicts = []
        if not theme_dicts:
            theme_dicts = _load_themes_from_disk()   # server not up yet: read them straight from disk
        if not theme_dicts:
            theme_dicts = [_FALLBACK_THEME]
        for t in theme_dicts:
            self.themes[t["name"]] = Theme(t)
            label = t["label"]
            self.theme_labels[t["name"]] = label[len("Invariantsmith "):] if label.startswith("Invariantsmith ") else label
        wanted = self.prefs.get("theme")
        active = wanted if wanted in self.themes else (
            config.DEFAULT_THEME if config.DEFAULT_THEME in self.themes else next(iter(self.themes)))
        self._apply_theme(self.themes[active])

    def _apply_theme(self, theme: Theme):
        self.current_theme = theme
        t = design.Tokens(theme)
        self.tokens = t
        icons.clear_cache()
        self.setStyleSheet(design.full_stylesheet(t))
        design.apply_palette(QApplication.instance(), t)
        self.editor.set_theme(theme)
        self.fix_panel.set_theme(theme)
        self.bottom.retheme(theme, t)
        self.sidebar.retheme(t)
        self.activity.retheme(t)
        self.title_bar.retheme(t)
        self.status.retheme(t)
        self.editor_area.retheme(t)
        self.toasts.tokens = t
        self.theme_btn.set_theme(theme, self.theme_labels.get(theme.name, theme.label), t)
        self._refresh_chrome_state()

    def _open_theme_picker(self):
        if not self.themes:
            return
        pop = ThemePopup(self.themes, self.theme_labels, self.current_theme.name, self.tokens)
        self._theme_before = self.current_theme
        pop.previewRequested.connect(self._queue_preview)
        pop.themeChosen.connect(self._choose_theme)
        pop.dismissed.connect(self._revert_preview)
        pos = self.theme_btn.mapToGlobal(self.theme_btn.rect().bottomRight())
        pop.adjustSize()
        pop.move(pos.x() - pop.width() + 6, pos.y() + 6)
        pop.show()
        self._theme_popup = pop

    def _queue_preview(self, name: str):
        self._preview_name = name
        if not hasattr(self, "_preview_timer"):
            self._preview_timer = QTimer(self)
            self._preview_timer.setSingleShot(True)
            self._preview_timer.setInterval(120)
            self._preview_timer.timeout.connect(self._do_preview)
        self._preview_timer.start()

    def _do_preview(self):
        n = self._preview_name
        if n and n in self.themes and self.themes[n] is not self.current_theme:
            self._apply_theme(self.themes[n])

    def _choose_theme(self, name: str):
        if hasattr(self, "_preview_timer"):
            self._preview_timer.stop()
        self._theme_before = None
        if name in self.themes:
            if self.themes[name] is not self.current_theme:
                self._apply_theme(self.themes[name])
            self.prefs.set("theme", name)
            self._toast(f"Theme: {self.theme_labels.get(name, name)}", "info", ms=1800)

    def _revert_preview(self):
        if hasattr(self, "_preview_timer"):
            self._preview_timer.stop()
        before = self._theme_before
        if before is not None and before is not self.current_theme:
            self._apply_theme(before)
        self._theme_before = None

    # ==================================================================
    # Documents & tabs
    # ==================================================================
    def _doc_by_id(self, doc_id: int):
        return next((d for d in self.editor.documents if d.id == doc_id), None)

    def _add_doc(self, doc):
        tab = self.title_bar.tabbar.add_tab(doc.id, doc.name, doc.language)
        doc.doc.modificationChanged.connect(lambda m, d=doc: self._on_modified(d, m))
        tab.set_modified(doc.modified)
        return tab

    def _next_untitled_name(self) -> str:
        self._untitled_n += 1
        return "Untitled" if self._untitled_n == 1 else f"Untitled-{self._untitled_n}"

    def _new_file(self, text: str = ""):
        d = self.editor.new_document(text if isinstance(text, str) else "", None, self._next_untitled_name())
        self._add_doc(d)
        self._switch_to(d)
        self.editor.setFocus()

    def _open_file_dialog(self):
        start = self.sidebar.folder() or ""
        paths, _ = QFileDialog.getOpenFileNames(self, "Open file", start, client_languages.file_filter_string())
        for p in paths:
            self._open_path(p)

    def _open_path(self, path: str, line: int | None = None):
        path = os.path.abspath(path)
        for d in self.editor.documents:
            if d.path and os.path.normcase(d.path) == os.path.normcase(path):
                self._switch_to(d)
                if line:
                    self.editor.goto_line(line)
                return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            QMessageBox.warning(self, "Can't open file", f"{os.path.basename(path)} isn't a UTF-8 text file.")
            return
        except OSError as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return
        name = os.path.basename(path)
        mode = client_languages.language_for_filename(name) or "auto"
        cur = self.editor.current
        reuse = (cur is not None and not cur.path and not cur.modified and len(self.editor.documents) == 1
                 and not cur.doc.toPlainText().strip())
        if reuse:
            # Adopt the empty scratch tab in place instead of closing it (closing the
            # last tab would spawn a fresh Untitled and leave two tabs).
            cur.path, cur.name, cur.mode = path, name, mode
            cur.doc.setPlainText(content)
            cur.doc.setModified(False)
            if cur.id not in self.title_bar.tabbar.tabs:
                self._add_doc(cur)
            self.editor.set_language(mode)
            self.title_bar.tabbar.set_active(cur.id)
            d = cur
            self._refresh_chrome_state()
        else:
            d = self.editor.new_document(content, path, name, mode, mode if mode != "auto" else "python")
            self._add_doc(d)
            self._switch_to(d)
        if line:
            self.editor.goto_line(line)
        self.prefs.push_recent("recent_files", path)
        self._rebuild_recent_menu()
        self._log(f"Opened {path}")
        self.editor.setFocus()

    def _open_folder_dialog(self):
        start = self.sidebar.folder() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Open folder", start)
        if folder:
            self._open_folder(folder)

    def _open_folder(self, folder: str):
        self.prefs.set("last_folder", folder)
        self.prefs.push_recent("recent_folders", folder)
        self.sidebar.set_folder(folder, self.prefs.get("recent_folders"))
        self._show_sidebar_page("explorer")
        self._refresh_chrome_state()
        self._log(f"Opened folder {folder}")

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        items = [p for p in self.prefs.get("recent_files") if os.path.exists(p)]
        if not items:
            self.recent_menu.addAction("No recent files").setEnabled(False)
            return
        for p in items[:10]:
            self.recent_menu.addAction(os.path.basename(p)).triggered.connect(lambda _=False, q=p: self._open_path(q))

    def _select_tab_by_id(self, doc_id: int):
        d = self._doc_by_id(doc_id)
        if d:
            self._switch_to(d)

    def _cycle_tab(self, step: int):
        order = self.title_bar.tabbar.order()
        if len(order) < 2 or self.editor.current is None:
            return
        i = order.index(self.editor.current.id)
        self._select_tab_by_id(order[(i + step) % len(order)])

    def _switch_to(self, d):
        if self.editor.current is d:
            self.title_bar.tabbar.set_active(d.id)
            return
        if self.fix_panel.has_error() and not self.fix_panel.is_pinned():
            self.fix_panel.reset_for_new_buffer()
        self.editor.set_current(d)

    def _on_document_switched(self, d):
        self.title_bar.tabbar.set_active(d.id)
        self._refresh_chrome_state()
        self.sidebar.schedule_history(d.name)
        self._refresh_outline()
        self._on_errors_changed(d.errors, from_switch=True)

    def _on_modified(self, d, modified: bool):
        tab = self.title_bar.tabbar.tabs.get(d.id)
        if tab:
            tab.set_modified(modified)
        if d is self.editor.current:
            self._refresh_title()

    def _refresh_title(self):
        d = self.editor.current
        if d is None:
            return
        dot = "\u25cf " if d.modified else ""
        self.setWindowTitle(f"{dot}{d.name} \u2014 InvariantSmith")

    def _refresh_chrome_state(self):
        d = self.editor.current
        if d is None:
            return
        self._refresh_title()
        tab = self.title_bar.tabbar.tabs.get(d.id)
        if tab:
            tab.set_name(d.name)
            tab.set_language(d.language)
            tab.set_modified(d.modified)
        label = client_languages.LANGUAGES.get(d.language, client_languages.PYTHON).label
        auto = " (auto)" if d.mode == "auto" else ""
        self.editor_area.set_language_label(label + auto, d.language)
        self.editor_area.set_path(self._breadcrumb_parts(d))
        interp = label
        if d.language == "python":
            v = sys.version_info
            interp = f"Python {v.major}.{v.minor}.{v.micro}"
        self.status.set_interpreter(interp + auto, d.language)
        self.sidebar.set_convert_source(d.language)
        self.title_bar.set_convert_source(d.language)
        for lid, act in self._convert_menu_actions.items():
            act.setEnabled(lid != d.language)

    def _breadcrumb_parts(self, d) -> list[str]:
        if not d.path:
            return [d.name]
        folder = self.sidebar.folder()
        try:
            if folder and os.path.commonpath([os.path.abspath(folder), d.path]) == os.path.abspath(folder):
                rel = os.path.relpath(d.path, folder).replace("\\", "/").split("/")
                return [os.path.basename(folder.rstrip("/\\"))] + rel
        except ValueError:
            pass
        parent = os.path.basename(os.path.dirname(d.path))
        return ([parent] if parent else []) + [d.name]

    def _close_current_tab(self):
        if self.editor.current:
            self._close_tab_by_id(self.editor.current.id)

    def _close_tab_by_id(self, doc_id: int):
        d = self._doc_by_id(doc_id)
        if d:
            self._close_doc(d)

    def _confirm_discard(self, d) -> bool:
        """True if it's OK to drop this document (saved, discarded, or unmodified)."""
        if not d.modified:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"Save changes to {d.name}?")
        box.setInformativeText("Your changes will be lost if you don't save them.")
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        disc = box.addButton("Don't Save", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return self._save(d)
        return clicked is disc

    def _close_doc(self, d):
        if not self._confirm_discard(d):
            return
        order = self.title_bar.tabbar.order()
        idx = order.index(d.id) if d.id in order else 0
        was_current = d is self.editor.current
        self.title_bar.tabbar.remove_tab(d.id)
        if was_current:
            remaining = [i for i in order if i != d.id]
            if remaining:
                self._switch_to(self._doc_by_id(remaining[min(idx, len(remaining) - 1)]))
            else:
                nd = self.editor.new_document("", None, self._next_untitled_name())
                self._add_doc(nd)
                self._switch_to(nd)
        self.editor.close_document(d)

    # ---- saving ----------------------------------------------------------
    def _save_current(self):
        if self.editor.current:
            self._save(self.editor.current)

    def _save_as_current(self):
        if self.editor.current:
            self._save(self.editor.current, force_dialog=True)

    def _save(self, d, force_dialog: bool = False) -> bool:
        path = d.path
        if force_dialog or not path:
            start = d.path or os.path.join(self.sidebar.folder() or "", d.name)
            if "." not in os.path.basename(start):
                start += client_languages.default_extension(d.language)
            path, _ = QFileDialog.getSaveFileName(self, "Save file", start, client_languages.file_filter_string())
            if not path:
                return False
        if self.prefs.get("tidy_on_save"):
            self.editor.tidy_document(d)
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(d.doc.toPlainText())
        except OSError as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return False
        d.path = path
        d.name = os.path.basename(path)
        by_ext = client_languages.language_for_filename(d.name)
        if by_ext and d.mode != by_ext:
            d.mode = by_ext
            if d is self.editor.current:
                self.editor.set_language(by_ext)
        d.doc.setModified(False)
        self.prefs.push_recent("recent_files", path)
        self._rebuild_recent_menu()
        self._refresh_chrome_state()
        self._toast(f"Saved {d.name}", "success", ms=1600)
        self._log(f"Saved {path}")
        folder = self.sidebar.folder()
        if folder:
            try:
                if os.path.commonpath([os.path.abspath(folder), path]) == os.path.abspath(folder):
                    self.sidebar.tree.reload()
            except ValueError:
                pass
        return True

    # ---- drag & drop -------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isdir(p):
                self._open_folder(p)
            elif os.path.isfile(p):
                self._open_path(p)

    # ==================================================================
    # Language
    # ==================================================================
    def _set_language(self, mode: str):
        self.editor.set_language(mode)
        self._refresh_chrome_state()

    def _language_menu(self):
        m = QMenu(self)
        cur = self.editor.language
        options = [("auto", "Auto-detect")] + [(l, client_languages.LANGUAGES[l].label)
                                               for l in client_languages.LANGUAGE_ORDER]
        for lid, label in options:
            act = m.addAction(("\u2713  " if lid == cur else "     ") + label)
            act.triggered.connect(lambda _=False, x=lid: self._set_language(x))
        btn = self.status.interp
        m.exec(btn.mapToGlobal(QPoint(0, 0)) - QPoint(0, m.sizeHint().height() + 4))

    def _on_language_detected(self, language_id: str):
        self._refresh_chrome_state()
        self._schedule_outline()

    # ==================================================================
    # Errors, problems, fixing
    # ==================================================================
    def _on_errors_changed(self, errors: list[dict], from_switch: bool = False):
        self.bottom.problems.set_errors(errors)
        n_err = sum(1 for e in errors if e.get("severity") == "syntax")
        n_warn = len(errors) - n_err
        self.bottom.set_problem_counts(n_err, n_warn)
        self.status.set_counts(n_err, n_warn)
        self.editor_area.set_health("errors" if n_err else ("warnings" if n_warn else "ok"))
        if from_switch:
            return
        # A fix shown for an error that no longer exists describes code that
        # isn't on screen anymore -- clear it (unless the user pinned it).
        shown = self.fix_panel.current_error()
        if (shown is not None and shown.get("source") != "run" and shown not in errors
                and not self.fix_panel.is_pinned()):
            self.fix_panel.reset_for_new_buffer()
        if self._pending_next:
            self._pending_next = False
            if errors:
                self._on_problem_activated(errors[0])
            else:
                self._toast("No more problems \u2014 nice.", "success")
        self.sidebar.schedule_history(self.editor.file_path)

    def _on_error_clicked(self, err: dict):
        """A click on an error line/marker -> request a fix. Repeat clicks on
        the same error don't re-fire the (expensive) model call; after a
        Reject or Accept the panel is empty, so a re-click works again."""
        self._show_right()
        if self.fix_panel.current_error() == err:
            return
        self._request_fix(err)

    def _request_fix(self, err: dict):
        self._log(f"Fix requested: {err.get('error_type', '')}: {err.get('message', '')} (line {err.get('line')})")
        self.fix_panel.request_fix(self.editor.file_path, self.editor.toPlainText(), err, self.editor.active_language)

    def _on_problem_activated(self, err: dict):
        self.editor.goto_line(err.get("line", 1), err.get("col") or None)
        self._on_error_clicked(err)

    def _fix_next_problem(self):
        errors = self.editor.current_errors
        if not errors:
            self._toast("No problems to fix.", "success", ms=1800)
            return
        self._on_problem_activated(errors[0])

    def _on_fix_accepted(self, new_code: str, apply_next: bool):
        # The server computed new_code from the buffer as it was when the fix
        # was requested. If the user has typed since, applying it would silently
        # wipe their edits -- refuse and ask for a fresh fix instead.
        if self.editor.toPlainText() != self.fix_panel.snapshot():
            self._toast("The file changed after this fix was generated \u2014 request a new fix.", "warn", ms=5000)
            return
        self.editor.setPlainText(new_code)
        self._log("Fix applied")
        self.editor.analyze_now()
        self.sidebar.schedule_history(self.editor.file_path)
        if apply_next:
            self._pending_next = True
            self._toast("Fix applied \u2014 looking for the next problem\u2026", "success", ms=1600)
        else:
            self._toast("Fix applied", "success", action=("Undo", self.editor.undo), ms=4500)

    # ==================================================================
    # Convert
    # ==================================================================
    def _convert_to(self, target_language: str):
        code = self.editor.toPlainText()
        if not code.strip():
            self._toast("Nothing to convert \u2014 the buffer is empty.", "warn")
            return
        if target_language == self.editor.active_language:
            self._toast("The file is already in that language.", "info")
            return
        target_label = client_languages.LANGUAGES[target_language].label
        # In auto mode active_language is just a cached guess; only forward a
        # concrete hint when the user actually pinned one.
        source_language = None if self.editor.language == "auto" else self.editor.active_language
        dialog = ConvertDialog(self.api_client, self.editor.file_path, code, source_language=source_language,
                               target_language=target_language, target_label=target_label,
                               theme=self.current_theme, parent=self)
        dialog.converted.connect(self._on_convert_accepted)
        dialog.exec()

    def _on_convert_accepted(self, converted_code: str, action_id: int):
        self.editor.setPlainText(converted_code)
        self.editor.set_language("auto")      # let detection confirm the new language...
        QTimer.singleShot(250, self._pin_to_detected_language)   # ...then pin it
        self._toast("Conversion applied", "success", action=("Undo", self.editor.undo), ms=5000)
        self._log("Conversion applied")

    def _pin_to_detected_language(self):
        d = self.editor.current
        if d is None:
            return
        detected = d.language
        self.editor.set_language(detected)
        if not d.path:
            ext = client_languages.default_extension(detected)
            if not d.name.endswith(ext):
                stem = d.name.rsplit(".", 1)[0] if "." in d.name else d.name
                d.name = stem + ext
        self._refresh_chrome_state()

    # ==================================================================
    # Run / Debug
    # ==================================================================
    def _run_code(self, debug: bool = False):
        code = self.editor.toPlainText()
        if not code.strip():
            self._toast("Nothing to run \u2014 the buffer is empty.", "warn")
            return
        if self.runner.is_running():
            self.runner.stop()
        d = self.editor.current
        language = self.editor.active_language
        self._run_language, self._run_name, self._run_debug = language, d.name, debug
        self._run_buffer = ""
        self._show_bottom_tab("terminal")
        term = self.bottom.terminal
        term.append_output(f"\n$ {'debug' if debug else 'run'} {d.name}  ({language})\n")
        stdin_text = term.stdin_text()
        if not stdin_text:
            pattern = _STDIN_READ_PATTERNS.get(language)
            if pattern and pattern.search(code):
                term.append_output(
                    "[Invariantsmith: this program reads input, but the stdin field above is "
                    "empty -- it'll see end-of-input immediately. If a read then fails "
                    "silently (e.g. scanf() on EOF), the variable it was reading into keeps "
                    "whatever was already in memory, which is why the output can look like "
                    "garbage or change between runs. Type the input it expects in the stdin "
                    "field and press Enter to re-run with it.]\n"
                )
        self._set_running(True)
        self.runner.run(language, code, stdin_text=stdin_text)

    def _stop_code(self):
        if not self.runner.is_running():
            return
        self.runner.stop()
        self.bottom.terminal.append_output("\n[Stopped]\n")
        self._set_running(False)

    def _set_running(self, running: bool):
        self.title_bar.set_running(running)
        self.sidebar.set_running(running)
        self.status.set_message("Running\u2026" if running else "")

    def _on_stdin_submitted(self, text: str):
        self._run_code(self._run_debug)

    def _on_run_output(self, text: str):
        wd = self.runner.work_dir()
        if wd:
            for fname in ("main.py", "main.c", "Main.java"):
                text = text.replace(os.path.join(wd, fname), self._run_name)
        self._run_buffer += text
        self.bottom.terminal.append_output(text)

    def _on_run_finished(self, exit_code: int):
        self.bottom.terminal.append_output(f"\n[Exited with code {exit_code}]\n")
        self._set_running(False)
        if exit_code == 0:
            self._toast("Finished successfully", "success", ms=1800)
            return
        diag = diagnose_output(self._run_language, self._run_buffer,
                               user_names=("main.py", "main.c", "Main.java", self._run_name))
        if not diag:
            self._toast(f"Exited with code {exit_code}", "warn")
            return
        self._last_run_error = diag
        summary = f"{diag['error_type']}: {diag['message']} (line {diag['line']})"
        if self._run_debug:
            self._toast(f"Debug found: {summary}", "error", ms=4000)
            self._show_right()
            self.editor.goto_line(diag["line"])
            self._request_fix(diag)
        else:
            self._toast(summary, "error", action=("Fix with AI", self._fix_last_run_error), ms=8000)

    def _fix_last_run_error(self):
        if self._last_run_error:
            self.editor.goto_line(self._last_run_error["line"])
            self._show_right()
            self._request_fix(self._last_run_error)

    def _on_run_failed_to_start(self, reason: str):
        self.bottom.terminal.append_output(f"\n[Error: {reason}]\n")
        self._set_running(False)
        self._toast(reason, "error")

    # ==================================================================
    # Misc UI actions
    # ==================================================================
    def _goto_line_dialog(self):
        n = self.editor.document().blockCount()
        line, ok = QInputDialog.getInt(self, "Go to line", f"Line number (1\u2013{n}):",
                                       self.editor.textCursor().blockNumber() + 1, 1, n)
        if ok:
            self.editor.goto_line(line)

    def _open_settings(self):
        dlg = SettingsDialog(self.prefs, self.tokens, self)
        dlg.changed.connect(self._on_setting_changed)
        dlg.exec()

    def _on_setting_changed(self, key: str, val):
        if key == "font_size":
            self.editor.apply_settings(font_size=val)
        elif key == "tab_width":
            self.editor.apply_settings(tab_width=val)
            self.editor_area.set_tab_width(val)
        elif key == "word_wrap":
            self.editor.apply_settings(word_wrap=val)
        elif key in ("auto_close", "suggestions", "indent_guides"):
            self.editor.apply_settings(**{key: bool(val)})
        elif key == "minimap":
            self.editor_area.set_minimap_visible(bool(val))
        elif key == "native_frame":
            self._toast("Restart InvariantSmith to change the window frame.", "info", ms=4500)

    def _toggle_pref(self, key: str, label: str):
        v = not bool(self.prefs.get(key))
        self.prefs.set(key, v)
        self._on_setting_changed(key, v)
        self._toast(f"{label} {'on' if v else 'off'}", "info", ms=1600)

    def _show_shortcuts(self):
        ShortcutsDialog(self.tokens, self).exec()

    def _tidy_current(self):
        d = self.editor.current
        if d is None:
            return
        self._toast("Whitespace tidied" if self.editor.tidy_document(d) else "Nothing to tidy", "info", ms=1600)

    _QUICK_OPEN_SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode",
                        ".pytest_cache", "build", "dist", "target", ".mypy_cache"}
    _QUICK_OPEN_EXT = (".py", ".c", ".h", ".java", ".txt", ".md", ".json", ".csv", ".cfg", ".toml", ".yml", ".yaml")

    def _quick_open(self):
        """Ctrl+P: fuzzy-pick a file from the open folder (or recent/open files)."""
        folder = self.sidebar.folder()
        paths: list[str] = []
        if folder and os.path.isdir(folder):
            root = os.path.abspath(folder)
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = sorted(x for x in dirs if x not in self._QUICK_OPEN_SKIP and not x.startswith("."))
                for fn in sorted(files):
                    if fn.lower().endswith(self._QUICK_OPEN_EXT):
                        paths.append(os.path.join(dirpath, fn))
                if len(paths) >= 4000:
                    break
        else:
            seen = set()
            for p in [d.path for d in self.editor.documents if d.path] + list(self.prefs.get("recent_files")):
                if p and p not in seen and os.path.isfile(p):
                    seen.add(p)
                    paths.append(p)
            if not paths:
                self._toast("Open a folder first (Ctrl+K) to jump between its files.", "info")
                return
        base = os.path.abspath(folder) if folder else ""
        cmds = []
        for p in paths:
            rel = os.path.relpath(p, base).replace("\\", "/") if base else p
            d = os.path.dirname(rel)
            title = os.path.basename(p) + (f"    {d}" if d else "")
            cmds.append((title, "", lambda p=p: self._open_path(p)))
        self.palette.open(cmds, "Go to file\u2026", keep_order=True)

    def _goto_symbol(self):
        """Ctrl+Shift+O: pick a function/class in the current file."""
        self._refresh_outline()
        ol = self.sidebar.outline
        cmds = []
        for i in range(ol.count()):
            it = ol.item(i)
            line = it.data(Qt.ItemDataRole.UserRole)
            cmds.append((it.text().strip(), f"line {line}", lambda ln=line: self.editor.goto_line(ln)))
        if not cmds:
            self._toast("No functions or classes found in this file.", "info")
            return
        self.palette.open(cmds, "Go to symbol\u2026", keep_order=True)

    def _show_notifications(self):
        m = QMenu(self)
        hist = self.toasts.history[-12:][::-1]
        if not hist:
            m.addAction("No notifications yet").setEnabled(False)
        for kind, text in hist:
            mark = {"success": "\u2713", "error": "\u2715", "warn": "\u26a0"}.get(kind, "\u2022")
            m.addAction(f"{mark}  {text}").setEnabled(False)
        btn = self.title_bar.bell_btn
        m.exec(btn.mapToGlobal(btn.rect().bottomRight()) - QPoint(m.sizeHint().width(), -4))

    def _toast(self, text: str, kind: str = "info", action=None, ms: int = 3200):
        self.toasts.show(text, kind, action, ms)

    def _log(self, text: str):
        self.bottom.output.append_output(f"[{time.strftime('%H:%M:%S')}] {text}\n")

    def _schedule_outline(self):
        self._outline_timer.start()

    def _refresh_outline(self):
        if self.editor.current is not None:
            self.sidebar.update_outline(self.editor.toPlainText(), self.editor.active_language)

    # ==================================================================
    # Model / server status polling
    # ==================================================================
    def _poll_model_status(self):
        w = _ModelStatusWorker(self.api_client)
        w.signals.finished.connect(self._on_model_status)
        w.signals.failed.connect(self._on_model_status_failed)
        self._pool.start(w)

    def _on_model_status(self, st: dict):
        prev_server, prev_model = self._server_state, self._model_state
        self._server_state = "ok"
        self.status.set_server("ok")
        state = st.get("state") or ("ready" if st.get("ready") else "loading")
        active = st.get("active_model") or {}
        name = active.get("filename") or ""
        self._model_state = state
        self.status.set_model(state, name)
        if prev_server == "down":
            self._toast("Reconnected to the local server.", "success", ms=2000)
            self.editor.analyze_now()
        if state == "ready" and prev_model in ("loading", "idle") and prev_server != "checking":
            self._toast("AI model is ready.", "success", ms=2000)
        if state in ("missing", "error") and prev_model != state:
            self._toast(st.get("error") or "The AI model couldn't be loaded.", "error", ms=7000)
        if state == "ready" and prev_model != "ready":
            self._log(f"AI model ready: {name}")
        self._poll_timer.start(3000 if state in ("loading", "idle") else 10000)

    def _on_model_status_failed(self):
        if self._server_state != "down":
            self._toast("Can't reach the local server (127.0.0.1:8731). Start it with uvicorn.", "error", ms=6000)
            self._log("Server unreachable")
        self._server_state = "down"
        self.status.set_server("down")
        self.status.set_model("idle", "")
        self._poll_timer.start(3000)

    def _model_clicked(self):
        msg = {"ready": "The AI model is loaded and ready.",
               "loading": "The AI model is still loading \u2014 the first fix request may be slow.",
               "missing": "No model file found in models/. Run scripts/download_model.sh.",
               "error": "The model failed to load. Check the server console for details.",
               "idle": "The model has not been loaded yet."}.get(self._model_state, "")
        self._toast(msg, "error" if self._model_state in ("missing", "error") else "info", ms=4500)

    # ==================================================================
    # Session
    # ==================================================================
    def _restore_session(self):
        geo = self.prefs.get("geometry")
        restored = False
        if geo:
            try:
                restored = bool(self.restoreGeometry(geo if isinstance(geo, QByteArray) else QByteArray(geo)))
            except Exception:
                restored = False
        if restored:
            scr = QGuiApplication.screenAt(self.geometry().center())
            if scr is None or not scr.availableGeometry().intersects(self.geometry()):
                restored = False
        if not restored:
            _fit_to_screen(self, 1360, 840)
        folder = self.prefs.get("last_folder")
        self.sidebar.set_folder(folder if folder and os.path.isdir(folder) else None, self.prefs.get("recent_folders"))

        # The editor starts with one scratch document; give it a tab, then let
        # the first restored file adopt it (see _open_path) or fill it with the demo.
        scratch = self.editor.current
        self._untitled_n = 1
        scratch.name = "Untitled"
        self._add_doc(scratch)
        self.title_bar.tabbar.set_active(scratch.id)
        files = [p for p in self.prefs.get("open_files") if os.path.isfile(p)]
        for p in files:
            self._open_path(p)
        if files:
            act = self.prefs.get("active_file")
            for d in self.editor.documents:
                if d.path and d.path == act:
                    self._switch_to(d)
        else:
            scratch.doc.setPlainText(SAMPLE_CODE)
            scratch.doc.setModified(False)
            self.editor.set_language("auto")
        self._on_document_switched(self.editor.current)

    def closeEvent(self, e: QCloseEvent):
        for d in list(self.editor.documents):
            if not self._confirm_discard(d):
                e.ignore()
                return
        self.runner.stop()
        p = self.prefs
        if not self.isMaximized():
            p.set("geometry", self.saveGeometry())
        p.set("open_files", [d.path for d in self.editor.documents if d.path])
        p.set("active_file", self.editor.current.path if self.editor.current and self.editor.current.path else "")
        p.set("bottom_tab", self.bottom.current_tab())
        p.sync()
        QApplication.instance().removeEventFilter(self.resizer)
        super().closeEvent(e)
