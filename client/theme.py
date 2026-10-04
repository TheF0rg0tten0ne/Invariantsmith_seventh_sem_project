"""
Loads themes/*.json (served by the API's /themes endpoint, or read
directly from disk if running the client standalone) and applies the
color tokens to the editor's palette and highlighter.
"""
from PySide6.QtGui import QPalette, QColor, QFont


class Theme:
    def __init__(self, data: dict):
        self.name = data["name"]
        self.label = data["label"]
        self.colors = data["colors"]

    def apply_to_editor_palette(self, editor) -> None:
        palette = editor.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(self.colors["background"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(self.colors["foreground"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(self.colors["selection"]))
        editor.setPalette(palette)

        font = QFont("Consolas, 'Fira Code', 'JetBrains Mono', monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(11)
        editor.setFont(font)

    def window_bg(self) -> QColor:
        return QColor(self.colors["background"])

    def panel_bg(self) -> QColor:
        """Slightly-lighter surface for title bar / suggestion panel, matching
        the original design mockup. Reuses the 'gutter' token rather than
        adding a new one to every themes/*.json file."""
        return QColor(self.colors.get("gutter", self.colors["background"]))

    def foreground(self) -> QColor:
        return QColor(self.colors["foreground"])

    def secondary_text(self) -> str:
        return self.colors.get("ai-ghost-text", self.colors["foreground"])

    def border(self) -> str:
        return self.colors.get("gutter", "#33333a")

    def error_color(self) -> QColor:
        return QColor(self.colors["error-underline"])

    def warning_color(self) -> QColor:
        return QColor(self.colors["warning-underline"])

    def gutter_bg(self) -> QColor:
        return QColor(self.colors["gutter"])

    def current_line_bg(self) -> QColor:
        """Subtle highlight for the line the caret is on. Derived from the
        gutter token at low alpha rather than a new theme file key, so all
        eight existing themes/*.json files get this for free instead of
        needing a token added to each one."""
        c = QColor(self.colors.get("gutter", self.colors["background"]))
        c.setAlpha(110)
        return c

    def diff_add_bg(self) -> QColor:
        return QColor(self.colors["diff-add-bg"])

    def diff_add_text(self) -> QColor:
        return QColor(self.colors["diff-add-text"])

    def diff_remove_bg(self) -> QColor:
        return QColor(self.colors["diff-remove-bg"])

    def diff_remove_text(self) -> QColor:
        return QColor(self.colors["diff-remove-text"])

    def accent(self) -> str:
        """Primary accent used for interactive highlights across the UI
        (language badge, active toolbar states, focus glows). Reuses the
        ai-suggestion-text token -- it's already a bright, theme-appropriate
        color in every themes/*.json file, so this is free instead of
        needing a new key added to all eight."""
        return self.colors.get("ai-suggestion-text", self.colors["foreground"])

    def accent_bg(self) -> str:
        return self.colors.get("ai-suggestion-bg", self.colors.get("gutter", self.colors["background"]))

    def scrollbar_css(self) -> str:
        """QScrollBar stylesheet matching the active theme. Qt renders
        scrollbars with the native OS style by default, which ignores our
        QPalette colors entirely -- on most platforms that means a plain
        white/grey bar sitting on top of a dark theme. This has to be set
        explicitly per-widget via setStyleSheet."""
        track = self.colors.get("gutter", self.colors["background"])
        handle = self.colors.get("ai-ghost-text", self.colors["foreground"])
        handle_hover = self.colors.get("selection", handle)
        return f"""
            QScrollBar:vertical {{
                background: {track};
                width: 12px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {handle};
                min-height: 24px;
                border-radius: 5px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {handle_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                background: {track};
                height: 12px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:horizontal {{
                background: {handle};
                min-width: 24px;
                border-radius: 5px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {handle_hover};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
                border: none;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """
