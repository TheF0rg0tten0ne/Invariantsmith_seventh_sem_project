"""Persistent user preferences (theme, layout, recent files, session).

Thin typed wrapper over QSettings so the rest of the client never touches
raw keys or worries about QSettings returning strings for ints/bools on
some platforms. Everything has a default, so a fresh install or a
corrupted settings file just behaves like a first run.
"""
import json

from PySide6.QtCore import QSettings

DEFAULTS = {
    "theme": "invariant_gold",
    "font_size": 11,
    "tab_width": 4,
    "word_wrap": False,
    "minimap": True,
    "auto_close": True,
    "suggestions": True,
    "indent_guides": True,
    "tidy_on_save": True,
    "native_frame": False,
    "sidebar_visible": True,
    "sidebar_page": "explorer",
    "bottom_visible": True,
    "bottom_tab": "problems",
    "right_visible": True,
    "sidebar_width": 248,
    "right_width": 392,
    "bottom_height": 200,
    "last_folder": "",
    "recent_folders": [],
    "recent_files": [],
    "open_files": [],
    "active_file": "",
    "geometry": None,
}


class Prefs:
    def __init__(self):
        self._s = QSettings("Invariantsmith", "Invariantsmith")

    def get(self, key: str):
        default = DEFAULTS.get(key)
        raw = self._s.value(key, default)
        if raw is None:
            return default
        try:
            if isinstance(default, bool):
                return raw if isinstance(raw, bool) else str(raw).lower() in ("true", "1", "yes")
            if isinstance(default, int):
                return int(raw)
            if isinstance(default, list):
                if isinstance(raw, list):
                    return raw
                if isinstance(raw, str):
                    return json.loads(raw) if raw.startswith("[") else ([raw] if raw else [])
                return list(default)
        except (ValueError, TypeError, json.JSONDecodeError):
            return default
        return raw

    def set(self, key: str, value) -> None:
        self._s.setValue(key, value)

    def push_recent(self, key: str, value: str, limit: int = 10) -> None:
        items = [v for v in self.get(key) if v != value]
        items.insert(0, value)
        self.set(key, items[:limit])

    def sync(self) -> None:
        self._s.sync()
