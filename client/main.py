#!/usr/bin/env python3
"""
Invariantsmith desktop client.

Run the API server first:
    uvicorn server.main:app --host 127.0.0.1 --port 8731

Then:
    python -m client.main
"""
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from . import design


def main():
    app = QApplication(sys.argv)
    # Fusion gives us a consistent, themeable base across platforms; the
    # native Windows style ignores most stylesheet and palette work.
    app.setStyle("Fusion")
    design.apply_app_font(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
