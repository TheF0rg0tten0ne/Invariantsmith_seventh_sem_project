"""Window chrome: title bar (logo menu, brand, document tabs, Run/Debug/Stop,
layout toggles, theme picker, notifications, window controls), the bottom
status bar, and a helper that makes the frameless window draggable/resizable.
"""
import sys

from PySide6.QtCore import Qt, QObject, QEvent, Signal, QSize, QPoint, QTimer
from PySide6.QtGui import QCursor, QFontMetrics
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import icons
from . import languages as client_languages
from .widgets import IconButton

TITLE_H = 52
STATUS_H = 28


# ---------------------------------------------------------------------------
# Document tabs
# ---------------------------------------------------------------------------
class DocTab(QFrame):
    clicked = Signal(int)
    closeClicked = Signal(int)

    def __init__(self, doc_id: int, name: str, language: str):
        super().__init__()
        self.doc_id = doc_id
        self.setObjectName("docTab")
        self.setProperty("active", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(34)
        self.setMaximumWidth(190)
        self.setMinimumWidth(96)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 4, 0)
        lay.setSpacing(7)
        self.icon = QLabel()
        self.icon.setPixmap(icons.lang_pixmap(language, 16))
        self.name = QLabel(name)
        self.name.setObjectName("docTabName")
        self.dot = QLabel()
        self.dot.setFixedSize(14, 14)
        self.close_btn = IconButton("x", "Close (Ctrl+W)", 20, 11, "muted", "tabClose")
        self.close_btn.clicked.connect(lambda: self.closeClicked.emit(self.doc_id))
        lay.addWidget(self.icon)
        lay.addWidget(self.name, stretch=1)
        lay.addWidget(self.dot)
        lay.addWidget(self.close_btn)
        self._modified = False
        self._full = name
        self._tokens = None

    def set_name(self, name: str):
        self._full = name
        self.setToolTip(name)
        self._elide()

    def _elide(self):
        fm = QFontMetrics(self.name.font())
        self.name.setText(fm.elidedText(self._full, Qt.TextElideMode.ElideMiddle, 120))

    def set_language(self, language: str):
        self.icon.setPixmap(icons.lang_pixmap(language, 16))

    def set_modified(self, m: bool):
        self._modified = m
        self._paint_dot()

    def set_active(self, a: bool):
        self.setProperty("active", a)
        self.style().unpolish(self)
        self.style().polish(self)

    def retheme(self, t):
        self._tokens = t
        self.close_btn.retheme(t)
        self._paint_dot()

    def _paint_dot(self):
        t = self._tokens
        if t is not None and self._modified:
            self.dot.setPixmap(icons.pixmap("dot", t.hex(t.accent), 10))
        else:
            self.dot.clear()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self.closeClicked.emit(self.doc_id)
        elif e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.doc_id)
        e.accept()


class DocTabBar(QScrollArea):
    tabSelected = Signal(int)
    tabCloseRequested = Signal(int)
    newTabRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(TITLE_H - 8)
        self.setMinimumWidth(130)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                           "QWidget#tabHost { background: transparent; }")
        host = QWidget()
        host.setObjectName("tabHost")
        self.row = QHBoxLayout(host)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.new_btn = IconButton("plus", "New file (Ctrl+N)", 30, 15, "muted", "chromeBtn")
        self.new_btn.clicked.connect(self.newTabRequested)
        self.row.addWidget(self.new_btn)
        self.row.addStretch()
        self.setWidget(host)
        self.tabs: dict[int, DocTab] = {}
        self._active = None
        self._tokens = None

    def add_tab(self, doc_id: int, name: str, language: str) -> DocTab:
        tab = DocTab(doc_id, name, language)
        tab.set_name(name)
        tab.clicked.connect(self.tabSelected)
        tab.closeClicked.connect(self.tabCloseRequested)
        self.row.insertWidget(self.row.count() - 2, tab)   # before [+] and the stretch
        self.tabs[doc_id] = tab
        if self._tokens:
            tab.retheme(self._tokens)
        return tab

    def remove_tab(self, doc_id: int):
        tab = self.tabs.pop(doc_id, None)
        if tab:
            self.row.removeWidget(tab)
            tab.deleteLater()

    def set_active(self, doc_id: int):
        self._active = doc_id
        for i, tab in self.tabs.items():
            tab.set_active(i == doc_id)
        tab = self.tabs.get(doc_id)
        if tab:
            QTimer.singleShot(0, lambda: self.ensureWidgetVisible(tab, 40, 0))

    def order(self) -> list[int]:
        out = []
        for i in range(self.row.count()):
            w = self.row.itemAt(i).widget()
            if isinstance(w, DocTab):
                out.append(w.doc_id)
        return out

    def wheelEvent(self, e):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - (e.angleDelta().y() or e.angleDelta().x()))

    def retheme(self, t):
        self._tokens = t
        self.new_btn.retheme(t)
        for tab in self.tabs.values():
            tab.retheme(t)


# ---------------------------------------------------------------------------
# Title bar
# ---------------------------------------------------------------------------
class TitleBar(QWidget):
    runClicked = Signal()
    debugClicked = Signal()
    stopClicked = Signal()
    convertRequested = Signal(str)   # target language id, e.g. "python"/"c"/"java"
    toggleSidebar = Signal()
    toggleBottom = Signal()
    toggleRight = Signal()
    settingsClicked = Signal()
    notificationsClicked = Signal()

    def __init__(self, window: QWidget, native_frame: bool):
        super().__init__()
        self.win = window
        self.native = native_frame
        self.setObjectName("appTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TITLE_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 0, 0)
        lay.setSpacing(8)

        self.logo = QToolButton()
        self.logo.setObjectName("logoBtn")
        self.logo.setFixedSize(34, 34)
        self.logo.setIconSize(QSize(20, 20))
        self.logo.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.logo.setToolTip("Menu")
        self.logo.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.logo)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.setContentsMargins(0, 0, 0, 0)
        self.brand_title = QLabel("InvariantSmith")
        self.brand_title.setObjectName("brandTitle")
        self.brand_sub = QLabel("AI Code Fixer \u2022 Offline")
        self.brand_sub.setObjectName("brandSub")
        brand.addWidget(self.brand_title)
        brand.addWidget(self.brand_sub)
        self.brand_box = QWidget()
        self.brand_box.setLayout(brand)
        lay.addWidget(self.brand_box)
        lay.addSpacing(10)

        self.tabbar = DocTabBar()
        lay.addWidget(self.tabbar, stretch=1)

        self.run_btn = QPushButton("  Run")
        self.run_btn.setObjectName("runPill")
        self.debug_btn = QPushButton("  Debug")
        self.debug_btn.setObjectName("debugPill")
        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("stopPill")
        self.stop_btn.setEnabled(False)
        self.run_hint = QLabel("F5")
        self.debug_hint = QLabel("F6")
        for b, tip in ((self.run_btn, "Run (F5)"), (self.debug_btn, "Run and diagnose failures with AI (F6)"),
                       (self.stop_btn, "Stop (Shift+F5)")):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip(tip)
        self.run_btn.setText("  Run   F5")
        self.debug_btn.setText("  Debug   F6")
        self.run_btn.clicked.connect(self.runClicked)
        self.debug_btn.clicked.connect(self.debugClicked)
        self.stop_btn.clicked.connect(self.stopClicked)
        lay.addWidget(self.run_btn)
        lay.addWidget(self.debug_btn)
        lay.addWidget(self.stop_btn)
        lay.addSpacing(6)

        # "Convert to <language>" -- also reachable from the sidebar's CONVERT
        # page, the right-click editor menu, and the command palette, but all
        # three are easy to miss, so a direct button sits in the title bar too.
        self.convert_btn = QPushButton("  Convert")
        self.convert_btn.setObjectName("convertPill")
        self.convert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.convert_btn.setToolTip("Convert this file to another language")
        self._convert_menu = QMenu(self.convert_btn)
        self._convert_menu_actions = {}
        for lid in client_languages.LANGUAGE_ORDER:
            act = self._convert_menu.addAction(client_languages.LANGUAGES[lid].label)
            act.triggered.connect(lambda _=False, t=lid: self.convertRequested.emit(t))
            self._convert_menu_actions[lid] = act
        self.convert_btn.setMenu(self._convert_menu)
        lay.addWidget(self.convert_btn)
        lay.addSpacing(10)

        self.side_btn = IconButton("layout-left", "Toggle sidebar (Ctrl+B)", 32, 17, checkable=True)
        self.bottom_btn = IconButton("layout-bottom", "Toggle panel (Ctrl+J)", 32, 17, checkable=True)
        self.right_btn = IconButton("layout-right", "Toggle Fix Insight (Ctrl+Alt+B)", 32, 17, checkable=True)
        self.side_btn.clicked.connect(self.toggleSidebar)
        self.bottom_btn.clicked.connect(self.toggleBottom)
        self.right_btn.clicked.connect(self.toggleRight)
        for b in (self.side_btn, self.bottom_btn, self.right_btn):
            lay.addWidget(b)
        self.theme_slot = QHBoxLayout()
        self.theme_slot.setContentsMargins(4, 0, 4, 0)
        lay.addLayout(self.theme_slot)
        self.bell_btn = IconButton("bell", "Notifications", 32, 17)
        self.bell_btn.clicked.connect(self.notificationsClicked)
        self.set_btn = IconButton("settings", "Settings (Ctrl+,)", 32, 17)
        self.set_btn.clicked.connect(self.settingsClicked)
        lay.addWidget(self.bell_btn)
        lay.addWidget(self.set_btn)

        self.win_box = QWidget()
        wl = QHBoxLayout(self.win_box)
        wl.setContentsMargins(6, 0, 0, 0)
        wl.setSpacing(0)
        self.min_btn = IconButton("minus", "Minimise", 46, 14, object_name="winBtn")
        self.max_btn = IconButton("maximize", "Maximise", 46, 13, object_name="winBtn")
        self.close_btn = IconButton("x", "Close", 46, 15, object_name="closeWinBtn")
        for b in (self.min_btn, self.max_btn, self.close_btn):
            b.setFixedHeight(TITLE_H)
            wl.addWidget(b)
        self.min_btn.clicked.connect(self.win.showMinimized)
        self.max_btn.clicked.connect(self.toggle_max)
        self.close_btn.clicked.connect(self.win.close)
        lay.addWidget(self.win_box)
        self.win_box.setVisible(not native_frame)
        self._tokens = None

    # -- helpers
    def set_running(self, running: bool):
        self.run_btn.setEnabled(not running)
        self.debug_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def set_convert_source(self, language: str):
        """Grey out 'Convert to <current language>' -- matches the sidebar's
        CONVERT page and the right-click menu, which do the same."""
        for lid, act in self._convert_menu_actions.items():
            act.setEnabled(lid != language)

    def set_status_text(self, text: str):
        self.brand_sub.setText(text)

    def toggle_max(self):
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()
        self.sync_max_icon()

    def sync_max_icon(self):
        self.max_btn.set_icon_name("restore" if self.win.isMaximized() else "maximize")
        self.max_btn.setToolTip("Restore" if self.win.isMaximized() else "Maximise")

    def set_compact(self, compact: bool):
        self.brand_box.setVisible(not compact)

    def retheme(self, t):
        self._tokens = t
        self.logo.setIcon(icons.icon("bolt", t.hex(t.on_accent), 20))
        self.tabbar.retheme(t)
        for b in (self.side_btn, self.bottom_btn, self.right_btn, self.bell_btn, self.set_btn,
                  self.min_btn, self.max_btn, self.close_btn):
            b.retheme(t)
        self.close_btn._color = lambda tk: (tk.hex(tk.text_muted), "#ffffff")
        self.close_btn.retheme(t)
        self.run_btn.setIcon(icons.icon("play", t.hex(t.accent), 15))
        self.debug_btn.setIcon(icons.icon("bug", t.hex(t.text_muted), 15))
        self.stop_btn.setIcon(icons.icon("stop", t.hex(t.text_muted), 14))
        self.convert_btn.setIcon(icons.icon("swap", t.hex(t.text_muted), 15))
        self.run_btn.setIconSize(QSize(15, 15))
        self.debug_btn.setIconSize(QSize(15, 15))
        self.convert_btn.setIconSize(QSize(15, 15))

    # -- drag to move / double-click maximise (custom frame only)
    def mousePressEvent(self, e):
        if not self.native and e.button() == Qt.MouseButton.LeftButton:
            wh = self.win.windowHandle()
            if wh is not None:
                wh.startSystemMove()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if not self.native and e.button() == Qt.MouseButton.LeftButton:
            self.toggle_max()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------
class StatusButton(QToolButton):
    def __init__(self, text: str = ""):
        super().__init__()
        self.setObjectName("statusBtn")
        self.setText(text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(14, 14))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class StatusBar(QWidget):
    problemsClicked = Signal()
    modelClicked = Signal()
    languageClicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("statusBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(STATUS_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(4)
        self.err_btn = StatusButton("0")
        self.warn_btn = StatusButton("0")
        self.err_btn.clicked.connect(self.problemsClicked)
        self.warn_btn.clicked.connect(self.problemsClicked)
        self.err_btn.setToolTip("Errors \u2014 click to open Problems")
        self.warn_btn.setToolTip("Warnings \u2014 click to open Problems")
        self.interp = StatusButton("Python")
        self.interp.setToolTip("Language and runtime used by Run")
        self.interp.clicked.connect(self.languageClicked)
        self.msg = QLabel("")
        self.msg.setObjectName("statusText")
        lay.addWidget(self.err_btn)
        lay.addWidget(self.warn_btn)
        lay.addSpacing(8)
        lay.addWidget(self.interp)
        lay.addSpacing(8)
        lay.addWidget(self.msg)
        lay.addStretch()
        self.offline = StatusButton("Offline Mode")
        self.offline.setToolTip("Everything runs locally: the model, the analysis and the server.")
        self.model = StatusButton("AI Model: \u2014")
        self.model.clicked.connect(self.modelClicked)
        lay.addWidget(self.offline)
        lay.addWidget(self.model)
        self._tokens = None
        self._server = "checking"
        self._model_state = "idle"
        self._model_name = ""

    def set_counts(self, errors: int, warnings: int):
        self.err_btn.setText(str(errors))
        self.warn_btn.setText(str(warnings))

    def set_message(self, text: str):
        self.msg.setText(text)

    def set_interpreter(self, text: str, language: str):
        self.interp.setText(text)
        self.interp.setIcon(icons.lang_icon(language, 14))

    def set_server(self, state: str):
        """'ok' | 'down' | 'checking'"""
        self._server = state
        self._paint()

    def set_model(self, state: str, name: str = ""):
        """state: ready | loading | missing | error | idle"""
        self._model_state, self._model_name = state, name
        self._paint()

    def retheme(self, t):
        self._tokens = t
        self.err_btn.setIcon(icons.icon("x-circle", t.hex(t.error), 14))
        self.warn_btn.setIcon(icons.icon("alert", t.hex(t.warning), 14))
        self._paint()

    def _paint(self):
        t = self._tokens
        if t is None:
            return
        if self._server == "ok":
            self.offline.setText("Offline Mode")
            self.offline.setIcon(icons.icon("dot", t.hex(t.success), 14))
        elif self._server == "down":
            self.offline.setText("Server unreachable")
            self.offline.setIcon(icons.icon("dot", t.hex(t.error), 14))
            self.offline.setToolTip("Start it with:  uvicorn server.main:app --host 127.0.0.1 --port 8731")
        else:
            self.offline.setText("Connecting\u2026")
            self.offline.setIcon(icons.icon("dot", t.hex(t.warning), 14))
        state = self._model_state
        label = {"ready": "ready", "loading": "loading\u2026", "missing": "model file missing",
                 "error": "failed to load", "idle": "not loaded"}.get(state, state)
        short = self._model_name.replace(".gguf", "") if self._model_name else "Invariant"
        col = {"ready": t.success, "loading": t.warning, "missing": t.error, "error": t.error}.get(
            state, t.text_muted)
        self.model.setText(f"AI Model: {short} (Local) \u00b7 {label}")
        self.model.setIcon(icons.icon("cpu", col.name(), 14))


# ---------------------------------------------------------------------------
# Frameless resize
# ---------------------------------------------------------------------------
class FramelessResizer(QObject):
    """App-wide event filter: within EDGE px of the window border, show a
    resize cursor and start a native system resize on press. (Child widgets
    cover the whole frameless window, so the window itself never sees these
    mouse events.)"""

    EDGE = 6

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.win = window
        self.enabled = True
        self._cursor_set = False

    def _edges(self, gpos) -> Qt.Edge:
        if self.win.isMaximized() or self.win.isFullScreen() or not self.win.isActiveWindow():
            return Qt.Edge(0)
        r = self.win.frameGeometry()
        x, y = gpos.x(), gpos.y()
        if not r.adjusted(-2, -2, 2, 2).contains(gpos):
            return Qt.Edge(0)
        e = Qt.Edge(0)
        if x - r.left() <= self.EDGE:
            e |= Qt.Edge.LeftEdge
        if r.right() - x <= self.EDGE:
            e |= Qt.Edge.RightEdge
        if y - r.top() <= self.EDGE:
            e |= Qt.Edge.TopEdge
        if r.bottom() - y <= self.EDGE:
            e |= Qt.Edge.BottomEdge
        return e

    @staticmethod
    def _cursor_for(e: Qt.Edge):
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if (e & L and e & T) or (e & R and e & B):
            return Qt.CursorShape.SizeFDiagCursor
        if (e & R and e & T) or (e & L and e & B):
            return Qt.CursorShape.SizeBDiagCursor
        if e & (L | R):
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def eventFilter(self, obj, ev):
        if not self.enabled:
            return False
        t = ev.type()
        if t not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self.win:
            return False
        gpos = ev.globalPosition().toPoint()
        edges = self._edges(gpos)
        if t == QEvent.Type.MouseMove:
            if edges:
                if not self._cursor_set:
                    QApplication.setOverrideCursor(QCursor(self._cursor_for(edges)))
                    self._cursor_set = True
                else:
                    QApplication.changeOverrideCursor(QCursor(self._cursor_for(edges)))
            elif self._cursor_set:
                QApplication.restoreOverrideCursor()
                self._cursor_set = False
            return False
        if edges and ev.button() == Qt.MouseButton.LeftButton:
            wh = self.win.windowHandle()
            if wh is not None:
                wh.startSystemResize(edges)
                return True
        return False
