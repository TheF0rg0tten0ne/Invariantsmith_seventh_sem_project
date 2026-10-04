"""
Fix Insight panel (right-hand side).

Layout follows the design mockup:

    FIX INSIGHT [AI]                      ...  pin  x
    +-------------------------------------------------+
    | (x) Undefined name 'bar'            90% verified |
    |     example.py:13:12                             |
    +-------------------------------------------------+
    Issue / Rationale / Suggested Fix (unified | side-by-side diff)
    [ Accept  Ctrl+Enter ] [ Reject ] [ Apply & Next  Alt+Enter ]
    v Checks & Verification
        (ok) All local checks passed

Behaviour notes
  * Everything between the header and the action row lives in a scroll area,
    so a small window scrolls the content instead of squashing it.
  * Every request carries an id; a slow response for an error the user has
    already moved on from is dropped instead of overwriting the newer one.
  * The server's `checks` list drives the Checks & Verification section, so
    the Rationale stays a clean explanation (older servers that only send the
    legacy bracketed notes inside `rationale` are still handled).
  * A fix that failed verification is shown for review, never auto-applied;
    the header menu offers 'Apply anyway' behind a confirmation.
"""
import re

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from . import icons
from .diff_view import DiffView
from .widgets import ActionButton, IconButton


# ---------------------------------------------------------------------------
# Workers (all network calls stay off the GUI thread)
# ---------------------------------------------------------------------------
class _Signals(QObject):
    # Connected only to bound methods of the panel (see _dispatch_*): a lambda
    # receiver would be destroyed with the worker and drop the queued result.
    finished = Signal(int, object)   # (token, payload)
    failed = Signal(int, str, bool)  # (token, message, stale -- see ApiError.stale)


class _CallWorker(QRunnable):
    def __init__(self, token: int, fn, *args):
        super().__init__()
        self.token, self.fn, self.args = token, fn, args
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.finished.emit(self.token, self.fn(*self.args))
        except Exception as e:  # noqa: BLE001 - surfaced to the user verbatim
            self.signals.failed.emit(self.token, str(e), getattr(e, "stale", False))


_BRACKET_RE = re.compile(r"\[(Invariantsmith:[^\]]*|Verif[^\]]*|Unverified[^\]]*|No effective[^\]]*)\]\s*")


def _split_legacy_rationale(text: str) -> tuple[str, list[dict]]:
    """Older servers inline their bookkeeping as [bracketed] notes inside the
    rationale. Peel those off into check rows so the Rationale reads clean."""
    checks = []
    for m in _BRACKET_RE.finditer(text):
        note = m.group(1).strip()
        low = note.lower()
        if low.startswith("verified"):
            status = "warn" if "other issue" in low else "pass"
        elif low.startswith(("verification failed", "unverified", "no effective")):
            status = "fail"
        else:
            status = "info"
        if low.startswith("unverified candidate"):
            continue   # redundant with the badge / failed check
        checks.append({"status": status, "text": note.removeprefix("Invariantsmith: ").strip()})
    clean = _BRACKET_RE.sub("", text).strip()
    return clean, checks


# ---------------------------------------------------------------------------
class SuggestionPanel(QWidget):
    fixAccepted = Signal(str, bool)   # (new code, apply_next)
    closeRequested = Signal()
    statusMessage = Signal(str, str)  # (text, kind) -> toast

    def __init__(self, api_client, theme=None):
        super().__init__()
        self.setObjectName("fixPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.api_client = api_client
        self.theme = theme
        self.tokens = None
        self._pool = QThreadPool.globalInstance()
        self._req_id = 0
        self._token = 0
        self._callbacks: dict = {}      # token -> (on_ok, on_fail)
        self._sev = None
        self._checks_data: list = []
        self._current_result: dict | None = None
        self._current_error: dict | None = None
        self._current_code = ""
        self._current_file_path = "Untitled"
        self._current_language = "python"
        self._pinned = False
        self._thinking_s = 0
        self._checks_open = True
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- header ---------------------------------------------------------
        header = QWidget()
        header.setFixedHeight(46)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 10, 0)
        hl.setSpacing(6)
        eyebrow = QLabel("FIX INSIGHT")
        eyebrow.setObjectName("panelEyebrow")
        ai = QLabel("AI")
        ai.setObjectName("aiTag")
        ai.setFixedHeight(18)
        ai.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(eyebrow)
        hl.addWidget(ai, alignment=Qt.AlignmentFlag.AlignVCenter)
        hl.addStretch()
        self.more_btn = IconButton("more", "More actions", size=26)
        self.pin_btn = IconButton("pin", "Keep this fix visible while you edit", size=26, checkable=True)
        self.close_btn = IconButton("x", "Hide panel", size=26)
        self.more_btn.clicked.connect(self._show_menu)
        self.pin_btn.toggled.connect(lambda v: setattr(self, "_pinned", v))
        self.close_btn.clicked.connect(self.closeRequested)
        for b in (self.more_btn, self.pin_btn, self.close_btn):
            hl.addWidget(b)
        root.addWidget(header)

        # -- scrollable body --------------------------------------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self.scroll = scroll
        body = QWidget()
        body.setObjectName("fixBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 2, 14, 14)
        bl.setSpacing(14)

        # issue card
        self.card = QFrame()
        self.card.setObjectName("issueCard")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.sev_icon = QLabel()
        self.sev_icon.setFixedSize(22, 22)
        self.title_label = QLabel("No issue selected")
        self.title_label.setObjectName("issueTitle")
        self.title_label.setWordWrap(True)
        self.badge = QLabel("")
        self.badge.setVisible(False)
        top.addWidget(self.sev_icon, alignment=Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.title_label, stretch=1)
        top.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignTop)
        cl.addLayout(top)
        self.loc_label = QLabel("")
        self.loc_label.setObjectName("issueLoc")
        self.loc_label.setContentsMargins(32, 0, 0, 0)
        cl.addWidget(self.loc_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setVisible(False)
        cl.addWidget(self.progress)
        bl.addWidget(self.card)

        # issue / rationale / explanation text blocks
        self.issue_title, self.issue_body = self._text_block(bl, "Issue")
        self.rationale_title, self.rationale_body = self._text_block(bl, "Rationale")
        self.explain_title, self.explain_body = self._text_block(bl, "Explanation")
        self.explain_title.setVisible(False)
        self.explain_body.setVisible(False)

        # suggested fix
        fix_head = QHBoxLayout()
        fix_head.setSpacing(8)
        self.fix_title = QLabel("Suggested Fix")
        self.fix_title.setObjectName("blockTitle")
        self.ai_gen = QLabel("AI-generated")
        self.ai_gen.setObjectName("aiGenerated")
        fix_head.addWidget(self.fix_title)
        fix_head.addWidget(self.ai_gen)
        fix_head.addStretch()
        self.unified_btn = QPushButton("Unified")
        self.split_btn = QPushButton("Side-by-side")
        self.unified_btn.setObjectName("toggleUnified")
        self.split_btn.setObjectName("toggleSplit")
        for b in (self.unified_btn, self.split_btn):
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.unified_btn.setChecked(True)
        self.unified_btn.clicked.connect(lambda: self._set_mode("unified"))
        self.split_btn.clicked.connect(lambda: self._set_mode("split"))
        fix_head.addWidget(self.unified_btn)
        fix_head.addWidget(self.split_btn)
        bl.addLayout(fix_head)

        self.diff = DiffView()
        self.diff.copyRequested.connect(self._on_copy_diff)
        bl.addWidget(self.diff)
        bl.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        # -- footer: actions + checks -----------------------------------------
        footer = QWidget()
        footer.setObjectName("fixFooter")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(14, 10, 14, 6)
        fl.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.accept_btn = ActionButton("Accept", "Ctrl+Enter", "primary")
        self.reject_btn = ActionButton("Reject", "", "secondary")
        self.next_btn = ActionButton("Apply & Next", "Alt+Enter", "secondary")
        for b, s in ((self.accept_btn, 5), (self.reject_btn, 2), (self.next_btn, 5)):
            b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)   # pure 5:2:5 split
            b.setMinimumWidth(58)
            row.addWidget(b, stretch=s)
        self.accept_btn.clicked.connect(lambda: self._on_accept(False))
        self.next_btn.clicked.connect(lambda: self._on_accept(True))
        self.reject_btn.clicked.connect(self._on_reject)
        fl.addLayout(row)

        self.checks_header = QPushButton("  Checks && Verification")
        self.checks_header.setObjectName("checksHeader")
        self.checks_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checks_header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.checks_header.clicked.connect(self._toggle_checks)
        fl.addSpacing(6)
        fl.addWidget(self.checks_header)
        self.checks_box = QWidget()
        self.checks_layout = QVBoxLayout(self.checks_box)
        self.checks_layout.setContentsMargins(4, 0, 0, 6)
        self.checks_layout.setSpacing(6)
        fl.addWidget(self.checks_box)
        root.addWidget(footer)

        self._set_empty_state()

    # -- small builders -------------------------------------------------------
    def _text_block(self, layout, title: str):
        t = QLabel(title)
        t.setObjectName("blockTitle")
        b = QLabel("")
        b.setObjectName("blockBody")
        b.setWordWrap(True)
        b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        b.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        wrap = QVBoxLayout()
        wrap.setSpacing(5)
        wrap.addWidget(t)
        wrap.addWidget(b)
        layout.addLayout(wrap)
        return t, b

    # -- theming ----------------------------------------------------------------
    def set_theme(self, theme):
        from . import design
        self.theme = theme
        t = design.Tokens(theme)
        self.tokens = t
        for b in (self.more_btn, self.pin_btn, self.close_btn):
            b.retheme(t)
        for b in (self.accept_btn, self.reject_btn, self.next_btn):
            b.retheme(t)
        self.diff.retheme(t)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; } QWidget#fixBody { background: transparent; }"
            + theme.scrollbar_css()
        )
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: {t.hex(t.hairline)}; border: none; border-radius: 1px; }}"
            f"QProgressBar::chunk {{ background: {t.hex(t.accent)}; border-radius: 1px; }}"
        )
        self._refresh_header_icon()
        self._render_badge()
        self._render_checks(self._checks_data)
        self._refresh_checks_chevron()

    # -- state --------------------------------------------------------------------
    def reset_for_new_buffer(self):
        self._timer.stop()
        self._req_id += 1          # invalidate anything still in flight
        self._current_result = None
        self._current_error = None
        self._current_code = ""
        self._set_empty_state()

    def snapshot(self) -> str:
        """The exact buffer text the current fix was generated for."""
        return self._current_code

    def has_error(self) -> bool:
        return self._current_error is not None

    def is_pinned(self) -> bool:
        return self._pinned

    def current_error(self):
        return self._current_error

    def _set_empty_state(self):
        self._sev = None
        self.title_label.setText("No issue selected")
        self.loc_label.setText("")
        self.badge.setVisible(False)
        self.progress.setVisible(False)
        self.issue_title.setVisible(True)
        self.issue_body.setText("Click a squiggle-underlined error in the editor, or a row in "
                                "Problems, to get an explained, verified fix.")
        self.rationale_title.setVisible(False)
        self.rationale_body.setVisible(False)
        self.explain_title.setVisible(False)
        self.explain_body.setVisible(False)
        self.diff.set_message("No fix yet.")
        self.diff.setFixedHeight(110)
        self._checks_data = []
        self._render_checks([])
        self.checks_header.setVisible(False)
        self.checks_box.setVisible(False)
        for b in (self.accept_btn, self.reject_btn, self.next_btn):
            b.setEnabled(False)
        self._refresh_header_icon()

    def _refresh_header_icon(self):
        t = self.tokens
        if t is None:
            return
        if self._sev is None:
            self.sev_icon.setPixmap(icons.pixmap("sparkle", t.hex(t.text_faint), 20))
        elif self._sev == "warning":
            self.sev_icon.setPixmap(icons.pixmap("alert", t.hex(t.warning), 20))
        else:
            self.sev_icon.setPixmap(icons.pixmap("x-circle", t.hex(t.error), 20))

    # -- request ----------------------------------------------------------------------
    def request_fix(self, file_path: str, code: str, error: dict, language: str = "python"):
        self._current_error = error
        self._current_code = code
        self._current_file_path = file_path
        self._current_language = language
        self._current_result = None

        msg = error.get("message", "")
        line, col = error.get("line"), error.get("column") or error.get("col")
        short = file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        loc = short + (f":{line}" + (f":{col}" if col else "") if line is not None else "")
        self._sev = "warning" if error.get("severity") in ("warning", "lint") else "error"
        self.title_label.setText(_headline(error))
        self.loc_label.setText(loc)
        self.issue_title.setVisible(True)
        self.issue_body.setText(msg or "No further detail supplied by the analyzer.")
        self.rationale_title.setVisible(True)
        self.rationale_body.setVisible(True)
        self.rationale_body.setText("")
        self.explain_title.setVisible(False)
        self.explain_body.setVisible(False)
        self.badge.setVisible(False)
        self._checks_data = []
        self._render_checks([])
        self.checks_header.setVisible(False)
        self.checks_box.setVisible(False)
        self._begin_thinking()
        self._refresh_header_icon()
        self._fire()

    def _begin_thinking(self):
        self._thinking_s = 0
        self.progress.setVisible(True)
        self.diff.set_message("Thinking\u2026 (0s)")
        self.diff.setFixedHeight(110)
        for b in (self.accept_btn, self.reject_btn, self.next_btn):
            b.setEnabled(False)
        self._timer.start()

    def _call(self, fn, args: tuple, on_ok, on_fail=None):
        """Run fn(*args) on the thread pool; deliver to on_ok/on_fail on the GUI thread."""
        self._token += 1
        token = self._token
        self._callbacks[token] = (on_ok, on_fail)
        w = _CallWorker(token, fn, *args)
        w.signals.finished.connect(self._dispatch_ok)
        w.signals.failed.connect(self._dispatch_fail)
        self._pool.start(w)

    def _dispatch_ok(self, token: int, payload):
        cb = self._callbacks.pop(token, None)
        if cb and cb[0]:
            cb[0](payload)

    def _dispatch_fail(self, token: int, message: str, stale: bool = False):
        cb = self._callbacks.pop(token, None)
        if cb and cb[1]:
            cb[1](message, stale)

    def _fire(self):
        self._req_id += 1
        rid = self._req_id
        e = self._current_error
        self._call(self.api_client.suggest_fix,
                   (self._current_file_path, self._current_code, e["error_type"], e["message"],
                    self._current_language, e.get("line")),
                   lambda res, rid=rid: self._on_result(rid, res),
                   lambda msg, stale=False, rid=rid: self._on_failed(rid, msg))

    def _tick(self):
        self._thinking_s += 1
        note = "  (the first request also loads the model)" if self._thinking_s >= 8 else ""
        self.diff.set_message(f"Thinking\u2026 ({self._thinking_s}s){note}")

    # -- result ---------------------------------------------------------------------------
    def _on_result(self, rid: int, result: dict):
        if rid != self._req_id:
            return   # the user moved on; a newer request owns the panel
        self._timer.stop()
        self.progress.setVisible(False)
        self._current_result = result
        diff = result.get("diff", "")
        verified = bool(result.get("verified", False))

        summary = result.get("summary")
        checks = result.get("checks")
        legacy = result.get("rationale", "")
        if summary is None or checks is None:
            summary_clean, legacy_checks = _split_legacy_rationale(legacy)
            summary = summary if summary is not None else summary_clean
            checks = checks if checks is not None else legacy_checks
        self.rationale_body.setText(summary or ("No explanation was produced for this fix."
                                                if diff else legacy))
        if diff:
            self.diff.set_diff(diff, self._current_code)
            self.diff.setFixedHeight(_diff_height(diff))
        else:
            self.diff.set_message(_no_fix_message(checks))
            self.diff.setFixedHeight(110)

        self.accept_btn.setEnabled(bool(diff) and verified)
        self.next_btn.setEnabled(bool(diff) and verified)
        self.reject_btn.setEnabled(True)
        self._checks_data = checks
        self._render_badge()
        self._render_checks(checks)
        self.checks_header.setVisible(True)
        if any(c.get("status") == "fail" for c in checks):
            self._checks_open = True
        self.checks_box.setVisible(self._checks_open)
        self._refresh_checks_chevron()

    def _on_failed(self, rid: int, message: str):
        if rid != self._req_id:
            return
        self._timer.stop()
        self.progress.setVisible(False)
        self.diff.set_message(f"Couldn't get a fix:\n{message}")
        self.rationale_body.setText("")
        self.reject_btn.setEnabled(True)
        self._checks_data = [{"status": "fail", "text": message}]
        self._render_checks(self._checks_data)
        self.checks_header.setVisible(True)
        self.checks_box.setVisible(True)
        self._refresh_checks_chevron()

    def _render_badge(self):
        r, t = self._current_result, self.tokens
        if not r or t is None:
            self.badge.setVisible(False)
            return
        conf = float(r.get("confidence", 0.0) or 0.0)
        verified = bool(r.get("verified", False))
        if verified and conf >= 0.85:
            fg, bg, text = t.diff_add_fg, t.diff_add_bg, f"{int(conf * 100)}% verified"
        elif verified:
            fg, bg, text = t.warning, t.hover, f"{int(conf * 100)}% verified"
        else:
            fg, bg, text = t.diff_rm_fg, t.diff_rm_bg, "Not verified"
        self.badge.setText(text)
        self.badge.setStyleSheet(
            f"color: {fg.name()}; background: {bg.name()}; border: 1px solid {fg.name()};"
            f"border-radius: 9px; padding: 2px 10px; font-size: 11px; font-weight: 700;"
        )
        self.badge.setVisible(True)

    # -- checks & verification ---------------------------------------------------------------
    def _render_checks(self, checks: list):
        lay = self.checks_layout
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.setParent(None)     # vanish immediately; deleteLater alone leaves it painted for a frame
                w.deleteLater()
        t = self.tokens
        if t is None:
            return
        for c in checks:
            status = c.get("status", "info")
            name, color = {"pass": ("check-circle", t.success), "fail": ("x-circle", t.error),
                           "warn": ("alert", t.warning)}.get(status, ("info", t.text_muted))
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            ic = QLabel()
            ic.setPixmap(icons.pixmap(name, color.name(), 16))
            ic.setFixedWidth(18)
            txt = QLabel(_check_text(c))
            txt.setWordWrap(True)
            txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            txt.setStyleSheet(f"color: {t.hex(t.text)}; font-size: 12px; background: transparent;")
            rl.addWidget(ic, alignment=Qt.AlignmentFlag.AlignTop)
            rl.addWidget(txt, stretch=1)
            lay.addWidget(row)

    def _toggle_checks(self):
        self._checks_open = not self._checks_open
        self.checks_box.setVisible(self._checks_open)
        self._refresh_checks_chevron()

    def _refresh_checks_chevron(self):
        if self.tokens is None:
            return
        self.checks_header.setIcon(icons.icon(
            "chevron-down" if self._checks_open else "chevron-right", self.tokens.hex(self.tokens.text_muted), 14))

    # -- mode / copy ---------------------------------------------------------------------------
    def _set_mode(self, mode: str):
        self.unified_btn.setChecked(mode == "unified")
        self.split_btn.setChecked(mode == "split")
        self.diff.set_mode(mode)
        if self._current_result and self._current_result.get("diff"):
            self.diff.setFixedHeight(_diff_height(self._current_result["diff"]))

    def _on_copy_diff(self):
        d = (self._current_result or {}).get("diff", "")
        if d:
            QGuiApplication.clipboard().setText(d)
            self.statusMessage.emit("Diff copied to clipboard", "info")

    # -- accept / reject ---------------------------------------------------------------------------
    def _on_accept(self, apply_next: bool):
        r = self._current_result
        if not r or not r.get("diff"):
            return
        self.accept_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self._call(self.api_client.apply_fix,
                   (self._current_file_path, r["action_id"], self._current_code, r["diff"], "accepted"),
                   lambda new_code: self._applied(new_code, apply_next), self._apply_failed)

    def _applied(self, new_code: str, apply_next: bool):
        self.fixAccepted.emit(new_code, apply_next)
        self.reset_for_new_buffer()

    def _apply_failed(self, msg: str, stale: bool = False):
        if stale:
            # Retrying changes nothing -- the diff's context no longer matches
            # the buffer (almost always because a different fix landed on
            # this file first). Keep Accept/Next disabled so the only way
            # forward is Regenerate, instead of leaving a doomed request one
            # click away.
            self.statusMessage.emit(f"{msg} (click Regenerate below)", "warn")
            self.accept_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            if self._current_result is not None:
                self._current_result["diff"] = ""
            self.diff.set_message("This suggestion is out of date \u2014 click Regenerate for a fresh fix.")
            return
        self.statusMessage.emit(f"Couldn't apply the fix: {msg}", "error")
        r = self._current_result
        ok = bool(r and r.get("verified") and r.get("diff"))
        self.accept_btn.setEnabled(ok)
        self.next_btn.setEnabled(ok)

    def _on_reject(self):
        r = self._current_result
        if r and r.get("action_id") is not None:
            self._call(self.api_client.reject_fix, (r["action_id"],), None)
        self.reset_for_new_buffer()

    # -- header menu ---------------------------------------------------------------------------------
    def _show_menu(self):
        m = QMenu(self)
        have_err = self._current_error is not None
        a = m.addAction("Regenerate fix")
        a.setEnabled(have_err)
        a.triggered.connect(self.regenerate)
        a = m.addAction("Explain this error")
        a.setEnabled(have_err)
        a.triggered.connect(self._on_explain)
        a = m.addAction("Copy diff")
        a.setEnabled(bool(self._current_result and self._current_result.get("diff")))
        a.triggered.connect(self._on_copy_diff)
        m.addSeparator()
        r = self._current_result
        a = m.addAction("Apply anyway (unverified)\u2026")
        a.setEnabled(bool(r and r.get("diff") and not r.get("verified")))
        a.triggered.connect(self._apply_anyway)
        m.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))

    def regenerate(self):
        if not self._current_error:
            return
        self._current_result = None
        self.badge.setVisible(False)
        self.rationale_body.setText("")
        self._checks_data = []
        self._render_checks([])
        self.checks_header.setVisible(False)
        self.checks_box.setVisible(False)
        self._begin_thinking()
        self._fire()

    def _apply_anyway(self):
        ans = QMessageBox.warning(
            self, "Apply unverified fix?",
            "This fix did not pass local verification. It may introduce new errors.\n\n"
            "You can undo it afterwards with Ctrl+Z. Apply it anyway?",
            QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ans == QMessageBox.StandardButton.Apply:
            self._on_accept(False)

    # -- explain -------------------------------------------------------------------------------------------
    def _on_explain(self):
        if not self._current_error:
            return
        self.explain_title.setVisible(True)
        self.explain_body.setVisible(True)
        self.explain_body.setText("Explaining\u2026")
        e = self._current_error
        self._call(self.api_client.explain,
                   (self._current_file_path, self._current_code, e["error_type"], e["message"],
                    self._current_language),
                   self.explain_body.setText,
                   lambda msg, stale=False: self.explain_body.setText(f"Couldn't get an explanation: {msg}"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _headline(error: dict) -> str:
    msg = error.get("message", "") or error.get("error_type", "") or "Issue detected"
    out = msg[0].upper() + msg[1:] if msg else msg
    return out if len(out) <= 90 else out[:87] + "\u2026"


def _check_text(c: dict) -> str:
    text = c.get("text", "")
    if c.get("status") == "pass" and text.startswith("Verified: the reported error is resolved"):
        return "All local checks passed"
    return text


def _no_fix_message(checks: list) -> str:
    for c in checks or []:
        if c.get("status") == "fail":
            return "No fix to show.\n" + c.get("text", "")
    return "(no usable fix produced)"


def _diff_height(diff: str) -> int:
    lines = sum(1 for l in diff.splitlines() if l[:1] in ("+", "-", " ", "@") and not l.startswith(("---", "+++")))
    return max(120, min(340, 28 + lines * 19))
