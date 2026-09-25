"""
===============================================================================
Desktop Document Translator GUI Application (Launcher)
===============================================================================

Note:
    The full desktop application implementation is located at:
    `backend.desktop.main`

Usage:
    python backend/main.py
    # or:
    python backend/desktop/main.py
===============================================================================
"""

from __future__ import annotations

import multiprocessing
import os
import sys

# Ensure project root is discoverable
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
for p in [project_root, current_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.desktop.main import App

__all__ = ["App"]

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = App()
    app.mainloop()
