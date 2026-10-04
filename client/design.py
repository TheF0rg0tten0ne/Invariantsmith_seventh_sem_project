"""
Central design layer for the Invariantsmith client.

Everything visual that is *shared* across panels lives here: the UI font
stack, spacing and radius scale, and one global Qt stylesheet generated from
the active theme's colour tokens. Individual widgets then only need to set
behaviour, plus a handful of local tweaks, instead of each one carrying its
own ad-hoc stylesheet string (which is what made the old UI look like a
collection of unrelated parts).

Colours come from themes/*.json. We derive a small set of surface tiers
(base, raised, sunken, hover) from the theme's background so every theme
gets a coherent elevation scale without requiring new keys in each file.
"""
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Scales
# ---------------------------------------------------------------------------
RADIUS_SM = 3
RADIUS_MD = 6
RADIUS_LG = 9

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16

UI_FAMILIES = ["Inter", "Segoe UI Variable", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Arial"]
MONO_FAMILIES = ["JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", "Menlo", "Courier New"]


def _first_available(families: list[str]) -> str | None:
    """Return the first installed family from the preference list. Returning
    None lets the caller keep Qt's own style-hint-driven default face, so a
    machine without any of our preferred fonts still gets a sensible one."""
    installed = set(QFontDatabase.families())
    for fam in families:
        if fam in installed:
            return fam
    return None


def ui_font(point_size: float = 10.0, weight: int = 400) -> QFont:
    family = _first_available(UI_FAMILIES)
    f = QFont(family) if family else QFont()
    f.setStyleHint(QFont.StyleHint.SansSerif)
    f.setPointSizeF(point_size)
    f.setWeight(QFont.Weight(weight) if isinstance(weight, int) else weight)
    return f


def mono_font(point_size: float = 10.5) -> QFont:
    family = _first_available(MONO_FAMILIES)
    f = QFont(family) if family else QFont()
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    f.setPointSizeF(point_size)
    return f


# ---------------------------------------------------------------------------
# Colour tiers derived from a theme
# ---------------------------------------------------------------------------
class Tokens:
    """Resolved colour roles for one theme. Built once per theme switch and
    handed to every panel, so the whole app agrees on what 'raised' or
    'muted' means."""

    def __init__(self, theme):
        c = theme.colors
        self.bg = QColor(c["background"])
        self.fg = QColor(c["foreground"])
        self.gutter = QColor(c.get("gutter", c["background"]))
        self.selection = QColor(c.get("selection", "#3a3f52"))
        self.accent = QColor(c.get("ai-suggestion-text", c["foreground"]))
        self.accent_bg = QColor(c.get("ai-suggestion-bg", c["background"]))
        self.error = QColor(c["error-underline"])
        self.warning = QColor(c["warning-underline"])
        self.muted_src = QColor(c.get("ai-ghost-text", c["foreground"]))
        self.diff_add_bg = QColor(c["diff-add-bg"])
        self.diff_add_fg = QColor(c["diff-add-text"])
        self.diff_rm_bg = QColor(c["diff-remove-bg"])
        self.diff_rm_fg = QColor(c["diff-remove-text"])

        dark = self.bg.lightness() < 128
        self.is_dark = dark
        step = 10 if dark else -8

        # Elevation ladder: sunken (editor) < base (window) < raised (chrome, cards)
        self.sunken = _shift(self.bg, -6 if dark else 4)
        self.base = self.bg
        self.raised = _shift(self.gutter, 0 if dark else 0)
        self.raised = QColor(self.gutter)
        self.hover = _shift(self.gutter, step)
        self.press = _shift(self.gutter, step * 2)

        # Hairline separators: a blend of fg into bg so they read as subtle
        # rules on any theme instead of a hard grey line.
        self.hairline = _mix(self.bg, self.fg, 0.14)
        self.hairline_strong = _mix(self.bg, self.fg, 0.24)

        self.text = self.fg
        self.text_muted = _mix(self.fg, self.bg, 0.45)
        self.text_faint = _mix(self.fg, self.bg, 0.62)

        # Surfaces for the app "chrome" (title bar, activity rail, status bar)
        # sit one step BELOW the editor, the sidebar one step above it -- the
        # same three-tier depth as the design mockup.
        self.frame = _shift(self.bg, -9 if dark else -10)
        self.sidebar = QColor(self.gutter)
        # Readable label colour for text drawn ON the accent colour (primary
        # buttons, the brand mark). A fixed near-black fails on the darker
        # accents light themes use.
        self.on_accent = QColor("#101116") if self.accent.lightness() > 135 else QColor("#ffffff")
        self.success = QColor(self.diff_add_fg)
        self.syntax = {k: QColor(c[k]) for k in
                       ("keyword", "string", "number", "comment", "function", "class", "variable")
                       if k in c}

    def hex(self, c: QColor) -> str:
        return c.name()

    def rgba(self, c: QColor, alpha: float) -> str:
        return f"rgba({c.red()},{c.green()},{c.blue()},{int(alpha * 255)})"


def _shift(c: QColor, amount: int) -> QColor:
    """Lighten (positive) or darken (negative) by an absolute amount per channel."""
    r = max(0, min(255, c.red() + amount))
    g = max(0, min(255, c.green() + amount))
    b = max(0, min(255, c.blue() + amount))
    return QColor(r, g, b)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend: t=0 -> a, t=1 -> b."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


# ---------------------------------------------------------------------------
# Global stylesheet
# ---------------------------------------------------------------------------
def build_stylesheet(t: Tokens) -> str:
    """One QSS document covering every shared widget class. Panels may still
    add tiny local overrides, but the defaults here make the whole window
    look intentional with no per-widget setup."""
    accent = t.hex(t.accent)
    fg = t.hex(t.text)
    muted = t.hex(t.text_muted)
    faint = t.hex(t.text_faint)
    base = t.hex(t.base)
    sunken = t.hex(t.sunken)
    raised = t.hex(t.raised)
    hover = t.hex(t.hover)
    press = t.hex(t.press)
    hair = t.hex(t.hairline)
    hair_s = t.hex(t.hairline_strong)
    sel = t.hex(t.selection)
    accent_bg = t.hex(t.accent_bg)

    return f"""
    QWidget {{
        color: {fg};
        font-size: 12px;
        selection-background-color: {sel};
        selection-color: {fg};
    }}
    QMainWindow, QDialog {{ background: {base}; }}
    QToolTip {{
        background: {raised}; color: {fg};
        border: 1px solid {hair_s}; border-radius: {RADIUS_SM}px;
        padding: 5px 8px;
    }}

    /* ---- menu bar --------------------------------------------------- */
    QMenuBar {{ background: {raised}; color: {muted}; padding: 2px 6px; }}
    QMenuBar::item {{ background: transparent; padding: 4px 9px; border-radius: {RADIUS_SM}px; }}
    QMenuBar::item:selected {{ background: {hover}; color: {fg}; }}
    QMenu {{
        background: {raised}; color: {fg};
        border: 1px solid {hair_s}; border-radius: {RADIUS_MD}px; padding: 5px;
    }}
    QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: {RADIUS_SM}px; }}
    QMenu::item:selected {{ background: {accent_bg}; color: {accent}; }}
    QMenu::separator {{ height: 1px; background: {hair}; margin: 4px 6px; }}

    /* ---- toolbar ---------------------------------------------------- */
    QToolBar {{
        background: {raised}; border: none;
        border-bottom: 1px solid {hair};
        padding: 5px 10px; spacing: 2px;
    }}
    QToolBar::separator {{ width: 1px; background: {hair}; margin: 5px 8px; }}
    QToolButton {{
        color: {muted}; background: transparent; border: 1px solid transparent;
        border-radius: {RADIUS_SM}px; padding: 5px 10px; font-size: 12px;
    }}
    QToolButton:hover {{ background: {hover}; color: {fg}; }}
    QToolButton:pressed {{ background: {press}; }}
    QToolButton:checked {{ background: {accent_bg}; color: {accent}; }}
    QToolButton:disabled {{ color: {faint}; }}
    QToolButton::menu-indicator {{ image: none; width: 0px; }}
    QToolButton#primaryAction {{
        color: #14151a; background: {accent};
        border: 1px solid {accent}; font-weight: 700;
        padding: 6px 16px; border-radius: {RADIUS_MD}px;
    }}
    QToolButton#primaryAction:hover {{ background: {fg}; border-color: {fg}; }}
    QToolButton#primaryAction:pressed {{ background: {accent}; }}
    QToolButton#dangerAction {{
        color: {fg}; background: transparent;
        border: 1px solid {hair_s}; padding: 6px 16px; border-radius: {RADIUS_MD}px;
    }}
    QToolButton#dangerAction:hover {{ border-color: {accent}; color: {accent}; }}
    QToolButton#dangerAction:disabled {{ color: {faint}; border-color: {hair}; }}

    /* ---- buttons ---------------------------------------------------- */
    QPushButton {{
        color: {fg}; background: {raised};
        border: 1px solid {hair}; border-radius: {RADIUS_SM}px;
        padding: 5px 12px; font-size: 12px;
    }}
    QPushButton:hover {{ background: {hover}; border-color: {hair_s}; }}
    QPushButton:pressed {{ background: {press}; }}
    QPushButton:disabled {{ color: {faint}; background: {base}; border-color: {hair}; }}
    QPushButton[flat="true"] {{
        background: transparent; border: none; color: {muted}; padding: 3px 6px;
    }}
    QPushButton[flat="true"]:hover {{ color: {fg}; background: {hover}; }}

    /* ---- inputs ----------------------------------------------------- */
    QComboBox {{
        color: {fg}; background: {raised};
        border: 1px solid {hair}; border-radius: {RADIUS_SM}px;
        padding: 3px 26px 3px 9px; font-size: 12px; min-height: 18px;
    }}
    QComboBox:hover {{ border-color: {hair_s}; }}
    QComboBox:focus {{ border-color: {accent}; }}
    QComboBox::drop-down {{ border: none; width: 22px; subcontrol-origin: padding; subcontrol-position: center right; }}
    QComboBox::down-arrow {{ width: 8px; height: 8px; }}
    QComboBox QAbstractItemView {{
        background: {raised}; color: {fg}; border: 1px solid {hair_s};
        border-radius: {RADIUS_MD}px; padding: 4px; outline: none;
        selection-background-color: {accent_bg}; selection-color: {accent};
    }}
    QLineEdit {{
        color: {fg}; background: {sunken};
        border: 1px solid {hair}; border-radius: {RADIUS_SM}px;
        padding: 5px 9px; font-size: 12px;
    }}
    QLineEdit:focus {{ border-color: {accent}; }}

    /* ---- text areas ------------------------------------------------- */
    QTextEdit, QPlainTextEdit {{
        background: {sunken}; color: {fg};
        border: 1px solid {hair}; border-radius: {RADIUS_MD}px;
    }}
    QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {hair_s}; }}

    /* ---- lists ------------------------------------------------------ */
    QListWidget {{
        background: transparent; color: {fg}; border: none; outline: none;
        font-size: 12px;
    }}
    QListWidget::item {{ padding: 6px 12px; border-radius: {RADIUS_SM}px; margin: 1px 6px; }}
    QListWidget::item:hover {{ background: {hover}; }}
    QListWidget::item:selected {{ background: {accent_bg}; color: {fg}; }}

    /* ---- progress --------------------------------------------------- */
    QProgressBar {{
        background: {sunken}; border: none; border-radius: 2px; max-height: 3px;
    }}
    QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}

    /* ---- splitter --------------------------------------------------- */
    /* Wider than a bare 1px hairline -- that's nearly impossible to grab
       accurately, which read as broken/rough rather than deliberate. The
       hover/pressed accent highlight gives a clear "this is draggable"
       affordance that a static line never does. */
    QSplitter::handle {{ background: {base}; }}
    QSplitter::handle:horizontal {{ width: 5px; margin: 0 1px; background: {hair}; }}
    QSplitter::handle:vertical {{ height: 5px; margin: 1px 0; background: {hair}; }}
    QSplitter::handle:horizontal:hover, QSplitter::handle:vertical:hover {{ background: {accent}; }}
    QSplitter::handle:horizontal:pressed, QSplitter::handle:vertical:pressed {{ background: {accent}; }}

    /* ---- status bar ------------------------------------------------- */
    QStatusBar {{
        background: {raised}; color: {muted};
        border-top: 1px solid {hair}; font-size: 11px;
    }}
    QStatusBar::item {{ border: none; }}
    QLabel#statusChip {{
        color: {muted}; background: transparent; padding: 0 8px; font-size: 11px;
    }}

    /* ---- scrollbars ------------------------------------------------- */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {hair_s}; min-height: 28px; border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {muted}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: {hair_s}; min-width: 28px; border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* ---- semantic labels ------------------------------------------- */
    QLabel#eyebrow {{
        color: {muted}; font-size: 10px; font-weight: 600;
        letter-spacing: 1px; background: transparent;
    }}
    QLabel#sectionTitle {{
        color: {fg}; font-size: 12px; font-weight: 600; background: transparent;
    }}
    QLabel#muted {{ color: {muted}; background: transparent; }}
    QLabel#brand {{
        color: {fg}; font-size: 13px; font-weight: 700; letter-spacing: 2px;
        background: transparent;
    }}
    QLabel#brandMark {{
        color: {base}; background: {accent};
        font-size: 13px; font-weight: 800;
        border-radius: {RADIUS_SM}px;
    }}
    QLabel#tagline {{
        color: {faint}; font-size: 9.5px; font-weight: 600;
        letter-spacing: 2px; background: transparent;
    }}
    QLabel#filename {{ color: {muted}; font-size: 12px; background: transparent; }}

    /* ---- panel cards & fix-insight chrome ---------------------------- */
    QFrame#panelCard {{
        background: {raised}; border: 1px solid {hair}; border-radius: {RADIUS_LG}px;
    }}
    QWidget#titleBar {{
        background: {raised}; border-bottom: 2px solid {accent};
    }}
    QLabel#severityDot {{
        color: #ffffff; background: {t.hex(t.error)};
        border-radius: 10px; font-weight: 800; font-size: 11px;
    }}
    QLabel#badgeGood {{
        color: {t.hex(t.diff_add_fg)}; background: {t.hex(t.diff_add_bg)};
        border: 1px solid {t.hex(t.diff_add_fg)}; border-radius: 9px;
        padding: 2px 9px; font-size: 11px; font-weight: 700;
    }}
    QLabel#badgeBad {{
        color: {t.hex(t.diff_rm_fg)}; background: {t.hex(t.diff_rm_bg)};
        border: 1px solid {t.hex(t.diff_rm_fg)}; border-radius: 9px;
        padding: 2px 9px; font-size: 11px; font-weight: 700;
    }}
    QLabel#footerBrand {{
        color: {faint}; font-size: 9px; font-weight: 700; letter-spacing: 2px;
        background: transparent;
    }}
    QFrame#footerStrip {{
        background: {sunken}; border: 1px solid {hair}; border-radius: {RADIUS_MD}px;
    }}
    QPushButton#toggleUnified, QPushButton#toggleSplit {{
        background: transparent; color: {muted}; border: 1px solid {hair};
        padding: 2px 10px; font-size: 10.5px; font-weight: 600;
    }}
    QPushButton#toggleUnified {{ border-top-left-radius: {RADIUS_SM}px; border-bottom-left-radius: {RADIUS_SM}px; border-right: none; }}
    QPushButton#toggleSplit {{ border-top-right-radius: {RADIUS_SM}px; border-bottom-right-radius: {RADIUS_SM}px; }}
    QPushButton#toggleUnified:checked, QPushButton#toggleSplit:checked {{
        background: {accent_bg}; color: {accent}; font-weight: 700;
    }}
    """


def build_chrome_stylesheet(t: Tokens) -> str:
    """Rules for the app chrome introduced with the three-column layout:
    title bar, activity rail, sidebar, bottom panel, status bar, document
    tabs, the Fix Insight card. Appended after build_stylesheet() so these
    win where selectors overlap."""
    h = t.hex
    accent, fg, muted, faint = h(t.accent), h(t.text), h(t.text_muted), h(t.text_faint)
    base, frame, side, raised = h(t.base), h(t.frame), h(t.sidebar), h(t.raised)
    sunken, hover, press = h(t.sunken), h(t.hover), h(t.press)
    hair, hair_s, accent_bg = h(t.hairline), h(t.hairline_strong), h(t.accent_bg)
    on_acc, err, ok = h(t.on_accent), h(t.error), h(t.success)

    return f"""
    /* ---- title bar ---------------------------------------------------- */
    QWidget#appTitleBar {{ background: {frame}; border-bottom: 1px solid {hair}; }}
    QLabel#brandTitle {{ color: {fg}; font-size: 13px; font-weight: 700; background: transparent; }}
    QLabel#brandSub {{ color: {faint}; font-size: 10.5px; background: transparent; }}
    QToolButton#logoBtn {{ background: {accent}; border: none; border-radius: 8px; padding: 0; }}
    QToolButton#logoBtn:hover {{ background: {fg}; }}
    QToolButton#logoBtn::menu-indicator {{ image: none; }}

    QToolButton#chromeBtn {{
        background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 0;
    }}
    QToolButton#chromeBtn:hover {{ background: {hover}; }}
    QToolButton#chromeBtn:pressed {{ background: {press}; }}
    QToolButton#chromeBtn:checked {{ background: {accent_bg}; }}
    QToolButton#chromeBtn:disabled {{ background: transparent; }}
    QToolButton#closeWinBtn {{ background: transparent; border: none; border-radius: 0; padding: 0; }}
    QToolButton#closeWinBtn:hover {{ background: #e5484d; }}
    QToolButton#winBtn {{ background: transparent; border: none; border-radius: 0; padding: 0; }}
    QToolButton#winBtn:hover {{ background: {hover}; }}

    QPushButton#runPill, QPushButton#debugPill, QPushButton#stopPill, QPushButton#convertPill {{
        background: {raised}; color: {fg}; border: 1px solid {hair_s};
        border-radius: 8px; padding: 6px 14px; font-size: 12px; font-weight: 600;
    }}
    QPushButton#runPill:hover, QPushButton#debugPill:hover, QPushButton#convertPill:hover {{ background: {hover}; border-color: {accent}; }}
    QPushButton#runPill:pressed, QPushButton#debugPill:pressed, QPushButton#convertPill:pressed {{ background: {press}; }}
    QPushButton#runPill:disabled, QPushButton#debugPill:disabled, QPushButton#convertPill:disabled {{ color: {faint}; background: {frame}; border-color: {hair}; }}
    QPushButton#stopPill {{ padding: 6px 10px; }}
    QPushButton#stopPill:hover:!disabled {{ border-color: {err}; }}
    QPushButton#stopPill:disabled {{ color: {faint}; background: {frame}; border-color: {hair}; }}

    /* ---- document tabs ------------------------------------------------ */
    QFrame#docTab {{
        background: transparent; border: 1px solid transparent; border-radius: 8px;
    }}
    QFrame#docTab:hover {{ background: {hover}; }}
    QFrame#docTab[active="true"] {{ background: {raised}; border: 1px solid {hair_s}; }}
    QLabel#docTabName {{ color: {muted}; font-size: 12px; background: transparent; }}
    QFrame#docTab[active="true"] QLabel#docTabName {{ color: {fg}; }}
    QToolButton#tabClose {{ background: transparent; border: none; border-radius: 4px; padding: 0; }}
    QToolButton#tabClose:hover {{ background: {press}; }}

    /* ---- activity rail ------------------------------------------------ */
    QWidget#activityBar {{ background: {frame}; border-right: 1px solid {hair}; }}
    QToolButton#activityBtn {{
        background: transparent; border: none; border-left: 2px solid transparent;
        border-radius: 0; padding: 0;
    }}
    QToolButton#activityBtn:hover {{ background: {hover}; }}
    QToolButton#activityBtn:checked {{ background: {raised}; border-left: 2px solid {accent}; }}

    /* ---- sidebar ------------------------------------------------------ */
    QWidget#sidebar {{ background: {side}; border-right: 1px solid {hair}; }}
    QWidget#sidebar QLabel {{ background: transparent; }}
    QLabel#sidebarTitle {{ color: {muted}; font-size: 10.5px; font-weight: 700; letter-spacing: 1.2px; }}
    QTreeWidget {{
        background: transparent; color: {fg}; border: none; outline: none; font-size: 12px;
    }}
    QTreeWidget::item {{ padding: 3px 2px; border-radius: 5px; margin: 0 4px; }}
    QTreeWidget::item:hover {{ background: {hover}; }}
    QTreeWidget::item:selected {{ background: {accent_bg}; color: {fg}; }}
    QTreeWidget::branch {{ background: transparent; }}
    QPushButton#sectionHeader {{
        background: transparent; color: {muted}; border: none; border-top: 1px solid {hair};
        border-radius: 0; text-align: left; padding: 7px 12px; font-size: 10.5px;
        font-weight: 700; letter-spacing: 1.2px;
    }}
    QPushButton#sectionHeader:hover {{ color: {fg}; background: {hover}; }}
    QPushButton#accentBtn {{
        background: {accent}; color: {on_acc}; border: 1px solid {accent};
        border-radius: 7px; padding: 7px 14px; font-weight: 700;
    }}
    QPushButton#accentBtn:hover:!disabled {{ background: {fg}; border-color: {fg}; color: {base}; }}
    QPushButton#accentBtn:disabled {{ background: transparent; color: {faint}; border-color: {hair}; }}
    QPushButton#ghostBtn {{
        background: transparent; color: {fg}; border: 1px solid {hair_s};
        border-radius: 7px; padding: 7px 14px;
    }}
    QPushButton#ghostBtn:hover:!disabled {{ border-color: {accent}; color: {accent}; }}
    QPushButton#ghostBtn:disabled {{ color: {faint}; border-color: {hair}; }}
    QPushButton#toolRow {{
        background: transparent; color: {fg}; border: 1px solid transparent; border-radius: 7px;
        text-align: left; padding: 8px 10px;
    }}
    QPushButton#toolRow:hover {{ background: {hover}; border-color: {hair}; }}

    /* ---- editor area -------------------------------------------------- */
    QWidget#editorArea {{ background: {base}; }}
    QWidget#breadcrumb {{ background: {base}; border-bottom: 1px solid {hair}; }}
    QLabel#crumb {{ color: {muted}; font-size: 11.5px; background: transparent; }}
    QLabel#crumbActive {{ color: {fg}; font-size: 11.5px; background: transparent; }}
    QWidget#infoStrip {{ background: {base}; border-top: 1px solid {hair}; }}
    QLabel#infoItem {{ color: {muted}; font-size: 11px; background: transparent; }}
    QWidget#findBar {{ background: {raised}; border-bottom: 1px solid {hair}; }}

    /* ---- bottom panel ------------------------------------------------- */
    QWidget#bottomPanel {{ background: {base}; border-top: 1px solid {hair}; }}
    QWidget#bottomHeader {{ background: {base}; border-bottom: 1px solid {hair}; }}
    QPushButton#bottomTab {{
        background: transparent; color: {muted}; border: none; border-bottom: 2px solid transparent;
        border-radius: 0; padding: 9px 12px 7px 12px; font-size: 11px; font-weight: 700;
        letter-spacing: 1px;
    }}
    QPushButton#bottomTab:hover {{ color: {fg}; }}
    QPushButton#bottomTab:checked {{ color: {fg}; border-bottom: 2px solid {accent}; }}
    QLabel#countPill {{
        color: {fg}; background: {press}; border-radius: 8px; padding: 0 6px;
        font-size: 10px; font-weight: 700;
    }}
    QLabel#countPillErr {{
        color: {on_acc}; background: {err}; border-radius: 8px; padding: 0 6px;
        font-size: 10px; font-weight: 700;
    }}
    QPlainTextEdit#console {{
        background: {base}; color: {fg}; border: none; padding: 8px 12px; border-radius: 0;
    }}
    QListWidget#problemList::item {{ padding: 6px 12px; margin: 1px 6px; }}

    /* ---- fix insight panel ------------------------------------------- */
    QWidget#fixPanel {{ background: {side}; border-left: 1px solid {hair}; }}
    QWidget#fixPanel QLabel {{ background: transparent; }}
    QLabel#panelEyebrow {{ color: {muted}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
    QLabel#aiTag {{
        color: {muted}; background: transparent; border: 1px solid {hair_s};
        border-radius: 4px; padding: 0 5px; font-size: 10px; font-weight: 700;
    }}
    QFrame#issueCard {{ background: {frame}; border: 1px solid {hair}; border-radius: 10px; }}
    QLabel#issueTitle {{ color: {fg}; font-size: 15px; font-weight: 700; }}
    QLabel#issueLoc {{ color: {muted}; font-size: 11.5px; }}
    QLabel#blockTitle {{ color: {fg}; font-size: 12.5px; font-weight: 700; }}
    QLabel#blockBody {{ color: {muted}; font-size: 12px; }}
    QLabel#aiGenerated {{ color: {ok}; font-size: 10.5px; font-weight: 600; }}
    QPushButton#fixAccept {{
        background: {accent}; color: {on_acc}; border: 1px solid {accent};
        border-radius: 8px; padding: 9px 10px; font-weight: 700; font-size: 12px;
    }}
    QPushButton#fixAccept:hover:!disabled {{ background: {fg}; border-color: {fg}; color: {base}; }}
    QPushButton#fixAccept:disabled {{ background: transparent; color: {faint}; border-color: {hair}; }}
    QPushButton#fixSecondary {{
        background: transparent; color: {fg}; border: 1px solid {hair_s};
        border-radius: 8px; padding: 9px 10px; font-weight: 600; font-size: 12px;
    }}
    QPushButton#fixSecondary:hover:!disabled {{ border-color: {accent}; color: {accent}; }}
    QPushButton#fixSecondary:disabled {{ color: {faint}; border-color: {hair}; }}
    QPushButton#checksHeader {{
        background: transparent; color: {fg}; border: none; border-top: 1px solid {hair};
        border-radius: 0; text-align: left; padding: 10px 2px; font-size: 12.5px; font-weight: 700;
    }}
    QPushButton#checksHeader:hover {{ color: {accent}; }}

    /* ---- status bar --------------------------------------------------- */
    QWidget#statusBar {{ background: {frame}; border-top: 1px solid {hair}; }}
    QLabel#statusText {{ color: {muted}; font-size: 11px; background: transparent; padding: 0 2px; }}
    QToolButton#statusBtn {{
        background: transparent; color: {muted}; border: none; border-radius: 4px;
        padding: 2px 7px; font-size: 11px;
    }}
    QToolButton#statusBtn:hover {{ background: {hover}; color: {fg}; }}

    /* ---- command palette / popups ------------------------------------ */
    QFrame#palette {{ background: {raised}; border: 1px solid {hair_s}; border-radius: 12px; }}
    QLineEdit#paletteInput {{
        background: transparent; border: none; border-bottom: 1px solid {hair};
        border-radius: 0; padding: 12px 14px; font-size: 14px;
    }}
    QListWidget#paletteList {{ background: transparent; }}
    QListWidget#paletteList::item {{ padding: 8px 12px; margin: 1px 6px; border-radius: 6px; }}
    QListWidget#paletteList::item:selected {{ background: {accent_bg}; color: {accent}; }}
    QFrame#popup {{ background: {raised}; border: 1px solid {hair_s}; border-radius: 12px; }}
    QFrame#toast {{
        background: {raised}; border: 1px solid {hair_s}; border-radius: 10px;
    }}
    QLabel#toastText {{ color: {fg}; font-size: 12px; background: transparent; }}
    """


def full_stylesheet(t: Tokens) -> str:
    return build_stylesheet(t) + build_chrome_stylesheet(t)


def apply_app_font(app: QApplication) -> None:
    """Set the application default font once at startup so anything that
    doesn't get explicit styling still picks up the same UI face."""
    app.setFont(ui_font(10.0))


def apply_palette(app: QApplication, t: Tokens) -> None:
    """Keep QPalette in step with the theme. Stylesheets cover most widgets,
    but native pieces (e.g. some popups, tooltips on certain platforms)
    still read the palette, so both must agree."""
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, t.base)
    pal.setColor(QPalette.ColorRole.WindowText, t.text)
    pal.setColor(QPalette.ColorRole.Base, t.sunken)
    pal.setColor(QPalette.ColorRole.AlternateBase, t.raised)
    pal.setColor(QPalette.ColorRole.Text, t.text)
    pal.setColor(QPalette.ColorRole.Button, t.raised)
    pal.setColor(QPalette.ColorRole.ButtonText, t.text)
    pal.setColor(QPalette.ColorRole.Highlight, t.selection)
    pal.setColor(QPalette.ColorRole.HighlightedText, t.text)
    pal.setColor(QPalette.ColorRole.ToolTipBase, t.raised)
    pal.setColor(QPalette.ColorRole.ToolTipText, t.text)
    app.setPalette(pal)
