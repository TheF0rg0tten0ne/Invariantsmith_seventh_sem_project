"""
Conversion preview dialog.

Cross-language conversion (Python <-> C <-> Java) has no meaningful
line-level diff the way a same-language fix does, so this shows the
result as a side-by-side whole-file preview instead of reusing
SuggestionPanel's diff view. Accepting replaces the editor's buffer
outright (and, since the target language is necessarily different from
the source, also switches the editor's pinned language and file
extension so highlighting/analysis follow along).
"""
from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QSplitter, QWidget, QProgressBar
)


class _WorkerSignals(QObject):
    finished = Signal(dict)
    failed = Signal(str)


class _ConvertWorker(QRunnable):
    def __init__(self, api_client, file_path, code, target_language, source_language):
        super().__init__()
        self.api_client = api_client
        self.file_path = file_path
        self.code = code
        self.target_language = target_language
        self.source_language = source_language
        self.signals = _WorkerSignals()

    def run(self):
        try:
            result = self.api_client.convert(
                self.file_path, self.code, self.target_language, self.source_language
            )
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.failed.emit(str(e))


def _mono_font():
    f = QFont("Consolas, 'Fira Code', monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(10)
    return f


class ConvertDialog(QDialog):
    converted = Signal(str, int)  # (converted_code, action_id) -- emitted only on Accept

    def __init__(self, api_client, file_path: str, code: str, source_language: str | None,
                 target_language: str, target_label: str, theme=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Convert to {target_label}")
        self.resize(880, 560)
        self.api_client = api_client
        self.file_path = file_path
        self.source_code = code
        self.source_language = source_language
        self.target_language = target_language
        self._result: dict | None = None
        self._thread_pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        self.status_label = QLabel(f"Converting to {target_label}…")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate -- CPU inference has no known duration
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        orig_lbl = QLabel("ORIGINAL")
        left_layout.addWidget(orig_lbl)
        self.original_view = QTextEdit()
        self.original_view.setReadOnly(True)
        self.original_view.setFont(_mono_font())
        self.original_view.setPlainText(code)
        left_layout.addWidget(self.original_view)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        conv_lbl = QLabel(f"CONVERTED · {target_label.upper()}")
        right_layout.addWidget(conv_lbl)
        self._column_labels = [orig_lbl, conv_lbl]
        self.converted_view = QTextEdit()
        self.converted_view.setReadOnly(True)
        self.converted_view.setFont(_mono_font())
        self.converted_view.setPlainText("Working…")
        right_layout.addWidget(self.converted_view)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.notes_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.accept_btn = QPushButton(f"Replace buffer with {target_label} version")
        self.accept_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.reject)
        self.accept_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.accept_btn)
        layout.addLayout(btn_row)

        if theme is not None:
            self._apply_theme(theme)

        self._start_conversion()

    def _apply_theme(self, theme):
        from . import design
        t = design.Tokens(theme)
        fg = t.hex(t.text)
        muted = t.hex(t.text_muted)
        faint = t.hex(t.text_faint)
        sunken = t.hex(t.sunken)
        raised = t.hex(t.raised)
        hair = t.hex(t.hairline)
        hair_s = t.hex(t.hairline_strong)
        add_fg = t.hex(t.diff_add_fg)
        add_bg = t.hex(t.diff_add_bg)
        self.setStyleSheet(f"background: {raised}; color: {fg};")
        for w in (self.original_view, self.converted_view):
            w.setFont(design.mono_font(10.0))
            w.setStyleSheet(
                f"QTextEdit {{ background: {sunken}; color: {fg}; border: 1px solid {hair}; "
                f"border-radius: 8px; padding: 8px; }}" + theme.scrollbar_css()
            )
        self.notes_label.setStyleSheet(f"font-size: 12px; color: {muted}; background: transparent; line-height: 150%;")
        self.status_label.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {fg}; background: transparent;")
        for lbl in getattr(self, '_column_labels', []):
            lbl.setStyleSheet(
                f"color: {faint}; font-size: 10px; font-weight: 600; letter-spacing: 1px; background: transparent;"
            )
        self.accept_btn.setStyleSheet(f"""
            QPushButton {{ background: {add_bg}; color: {add_fg};
                border: 1px solid {hair}; border-radius: 6px; padding: 7px 16px; font-weight: 600; }}
            QPushButton:hover:!disabled {{ border-color: {add_fg}; }}
            QPushButton:disabled {{ color: {faint}; background: transparent; }}
        """)
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {muted};
                border: 1px solid {hair}; border-radius: 6px; padding: 7px 16px; }}
            QPushButton:hover {{ color: {fg}; border-color: {hair_s}; }}
        """)

    def _start_conversion(self):
        worker = _ConvertWorker(
            self.api_client, self.file_path, self.source_code,
            self.target_language, self.source_language,
        )
        worker.signals.finished.connect(self._on_result)
        worker.signals.failed.connect(self._on_failed)
        self._thread_pool.start(worker)

    def _on_result(self, result: dict):
        self.progress.setVisible(False)
        self._result = result
        if result.get("ok") and result.get("converted_code"):
            self.converted_view.setPlainText(result["converted_code"])
            self.status_label.setText("Conversion ready -- review before replacing your buffer.")
            self.accept_btn.setEnabled(True)
        else:
            self.converted_view.setPlainText("(no usable conversion produced)")
            self.status_label.setText("Conversion failed.")
        self.notes_label.setText(result.get("notes", ""))

    def _on_failed(self, message: str):
        self.progress.setVisible(False)
        self.converted_view.setPlainText(f"Error requesting conversion: {message}")
        self.status_label.setText("Conversion failed.")

    def _on_accept(self):
        if not self._result or not self._result.get("ok"):
            return
        try:
            self.api_client.convert_apply(
                self.file_path, self._result["action_id"], outcome="accepted"
            )
        except Exception:
            pass  # logging failure shouldn't block the user from getting their code
        self.converted.emit(self._result["converted_code"], self._result["action_id"])
        self.accept()

    def reject(self):
        if self._result and self._result.get("ok"):
            try:
                self.api_client.convert_apply(
                    self.file_path, self._result["action_id"], outcome="rejected"
                )
            except Exception:
                pass
        super().reject()
