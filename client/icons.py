"""
Icon factory. Every glyph is an inline SVG drawn on a 24x24 grid and tinted
at render time, so icons follow the active theme (accent, muted, danger...)
with no image assets to ship and crisp rendering at any DPI.

    icons.icon("play", "#e0b454")            -> QIcon
    icons.pixmap("bug", "#888", 16)          -> QPixmap
    icons.lang_icon("python", 16)            -> small coloured language badge
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QGuiApplication
from PySide6.QtSvg import QSvgRenderer

# name -> (svg body, filled?)   Stroke icons use stroke="currentColor".
_ICONS: dict[str, tuple[str, bool]] = {
    "files": ('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>', False),
    "file": ('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>', False),
    "search": ('<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>', False),
    "git": ('<circle cx="6" cy="5.5" r="2"/><circle cx="6" cy="18.5" r="2"/><circle cx="18" cy="9" r="2"/>'
            '<path d="M6 7.5v9"/><path d="M18 11v.5a3 3 0 0 1-3 3H9.5a3.5 3.5 0 0 0-3.5 3"/>', False),
    "play": ('<path d="M7 4.5v15l12.5-7.5z"/>', True),
    "bug": ('<rect x="8" y="8.5" width="8" height="11" rx="4"/><path d="M9.5 8.5V7a2.5 2.5 0 0 1 5 0v1.5"/>'
            '<path d="M4 13h4M16 13h4M5 7.5l3 2M19 7.5l-3 2M5 19l3-2M19 19l-3-2M12 12v7"/>', False),
    "package": ('<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>', False),
    "terminal": ('<rect x="3" y="4.5" width="18" height="15" rx="2.2"/><path d="M7 9.5l3 2.5-3 2.5M13 15h4"/>', False),
    "settings": ('<circle cx="12" cy="12" r="3"/><path d="M12 2.5v2.8M12 18.7v2.8M2.5 12h2.8M18.7 12h2.8'
                 'M5.3 5.3l2 2M16.7 16.7l2 2M5.3 18.7l2-2M16.7 7.3l2-2"/><circle cx="12" cy="12" r="6.6"/>', False),
    "bell": ('<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>', False),
    "keyboard": ('<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M7.5 14h9"/>', False),
    "folder": ('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', False),
    "folder-open": ('<path d="M3 17.5V6.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2V10"/>'
                    '<path d="M3 17.5l2.4-6.6a1.5 1.5 0 0 1 1.4-1h14.4a1 1 0 0 1 1 1.3L19.7 18a2 2 0 0 1-1.9 1.4H5a2 2 0 0 1-2-1.9z"/>', False),
    "chevron-right": ('<path d="M9 6l6 6-6 6"/>', False),
    "chevron-down": ('<path d="M6 9l6 6 6-6"/>', False),
    "chevron-up": ('<path d="M6 15l6-6 6 6"/>', False),
    "x": ('<path d="M6 6l12 12M18 6L6 18"/>', False),
    "plus": ('<path d="M12 5v14M5 12h14"/>', False),
    "minus": ('<path d="M5 12h14"/>', False),
    "maximize": ('<rect x="5.5" y="5.5" width="13" height="13" rx="1.5"/>', False),
    "restore": ('<rect x="4.5" y="8.5" width="11" height="11" rx="1.5"/><path d="M8.5 8.5V6a1.5 1.5 0 0 1 1.5-1.5h8A1.5 1.5 0 0 1 19.5 6v8a1.5 1.5 0 0 1-1.5 1.5h-2.5"/>', False),
    "copy": ('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6.5A2 2 0 0 1 7 4.5h8.5"/>', False),
    "pin": ('<path d="M9 4h6l-1 6 3 3H7l3-3z"/><path d="M12 13v7"/>', False),
    "more": ('<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>', True),
    "layout-left": ('<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M9.5 4.5v15"/>', False),
    "layout-bottom": ('<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M3 14h18"/>', False),
    "layout-right": ('<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M14.5 4.5v15"/>', False),
    "stop": ('<rect x="6" y="6" width="12" height="12" rx="1.8"/>', True),
    "check": ('<path d="M5 12.5l4.5 4.5L19 7"/>', False),
    "x-circle": ('<circle cx="12" cy="12" r="8.5"/><path d="M9 9l6 6M15 9l-6 6"/>', False),
    "check-circle": ('<circle cx="12" cy="12" r="8.5"/><path d="M8.2 12.4l2.7 2.7 5-5.6"/>', False),
    "alert": ('<path d="M12 4l9 15.5H3z"/><path d="M12 10v4M12 16.8h.01"/>', False),
    "info": ('<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/>', False),
    "trash": ('<path d="M4 7h16M10 7V4.5h4V7M6 7l1 13h10l1-13M10 11v5.5M14 11v5.5"/>', False),
    "split": ('<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M12 4.5v15"/>', False),
    "refresh": ('<path d="M20 11.5A8 8 0 1 0 17.7 17"/><path d="M20.5 4.5v6.5H14"/>', False),
    "palette": ('<path d="M12 3a9 9 0 1 0 0 18c1.2 0 2-.8 2-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.8 1.8-1.8H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z"/>'
                '<circle cx="7.5" cy="11.5" r="1"/><circle cx="10" cy="7.5" r="1"/><circle cx="15" cy="7.5" r="1"/>', False),
    "sparkle": ('<path d="M11 3.5l1.8 5.2 5.2 1.8-5.2 1.8L11 17.5l-1.8-5.2L4 10.5l5.2-1.8z"/><path d="M19 15l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>', False),
    "save": ('<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>', False),
    "swap": ('<path d="M4 8h14l-3-3M20 16H6l3 3"/>', False),
    "list": ('<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>', False),
    "clock": ('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>', False),
    "bolt": ('<path d="M13.5 2.5L5 13.5h6.2l-1 8 8.8-11.5h-6.3z"/>', True),
    "arrow-up": ('<path d="M12 19V5M6 11l6-6 6 6"/>', False),
    "arrow-down": ('<path d="M12 5v14M6 13l6 6 6-6"/>', False),
    "case": ('<path d="M3 17l4-10 4 10M4.6 13h4.8M14 17v-4.5a2.2 2.2 0 0 1 4.4 0V17M14 14.5h4.4"/>', False),
    "regex": ('<path d="M6 17v.01M12 5v9M8 7.5l8 4M16 7.5l-8 4"/>', False),
    "wrap": ('<path d="M4 6h16M4 12h12a3 3 0 0 1 0 6h-3M4 18h5"/><path d="M15 16l-2 2 2 2"/>', False),
    "zoom-in": ('<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2M11 8.5v5M8.5 11h5"/>', False),
    "home": ('<path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/>', False),
    "dot": ('<circle cx="12" cy="12" r="4"/>', True),
    "zap-off": ('<path d="M13.5 2.5L5 13.5h6.2l-1 8M17 9.5l2 .0-3 4"/><path d="M3 3l18 18"/>', False),
    "wifi-off": ('<path d="M3 3l18 18M8.5 16.5a5 5 0 0 1 7 0M5 12.9a10 10 0 0 1 4.2-2.4M12 20h.01M19 12.9a10 10 0 0 0-5-2.7"/>', False),
    "cpu": ('<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx=".8"/>'
            '<path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>', False),
    "undo": ('<path d="M9 7L4.5 11.5 9 16"/><path d="M5 11.5h9.5a5 5 0 0 1 0 10H11"/>', False),
    "bolt-outline": ('<path d="M13.5 2.5L5 13.5h6.2l-1 8 8.8-11.5h-6.3z"/>', False),
}


def _svg(name: str, color: str, stroke: float) -> bytes:
    body, filled = _ICONS.get(name, _ICONS["dot"])
    if filled:
        attrs = f'fill="{color}" stroke="{color}" stroke-width="1.4" stroke-linejoin="round"'
    else:
        attrs = (f'fill="none" stroke="{color}" stroke-width="{stroke}" '
                 f'stroke-linecap="round" stroke-linejoin="round"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {attrs}>{body}</svg>').encode()


def _dpr() -> float:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app else None
    return screen.devicePixelRatio() if screen else 1.0


@lru_cache(maxsize=1024)
def _pixmap(name: str, color: str, size: int, stroke: float, dpr: float) -> QPixmap:
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def pixmap(name: str, color: str = "#cccccc", size: int = 16, stroke: float = 1.9) -> QPixmap:
    return _pixmap(name, color, size, stroke, _dpr())


def icon(name: str, color: str = "#cccccc", size: int = 18, hover: str | None = None,
         disabled: str | None = None, stroke: float = 1.9) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size, stroke), QIcon.Mode.Normal)
    ic.addPixmap(pixmap(name, hover or color, size, stroke), QIcon.Mode.Active)
    ic.addPixmap(pixmap(name, hover or color, size, stroke), QIcon.Mode.Selected)
    if disabled:
        ic.addPixmap(pixmap(name, disabled, size, stroke), QIcon.Mode.Disabled)
    return ic


# --- language badges -----------------------------------------------------
LANG_COLORS = {"python": "#4b8bbe", "c": "#5b8fd6", "java": "#e07b39"}
LANG_LETTERS = {"python": "Py", "c": "C", "java": "J"}


@lru_cache(maxsize=64)
def _lang_pixmap(language: str, size: int, dpr: float) -> QPixmap:
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    color = QColor(LANG_COLORS.get(language, "#8a8f9c"))
    p.setBrush(color)
    p.drawRoundedRect(QRectF(0, 0, px, px), px * 0.24, px * 0.24)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(max(6, int(px * (0.5 if len(LANG_LETTERS.get(language, "?")) == 1 else 0.42))))
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, LANG_LETTERS.get(language, "?"))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def lang_pixmap(language: str, size: int = 16) -> QPixmap:
    return _lang_pixmap(language, size, _dpr())


def lang_icon(language: str, size: int = 16) -> QIcon:
    return QIcon(lang_pixmap(language, size))


def clear_cache() -> None:
    _pixmap.cache_clear()
    _lang_pixmap.cache_clear()
