"""
===============================================================================
Desktop Application Subpackage
===============================================================================

Purpose:
    Exposes the CustomTkinter desktop graphical user interface, worker process
    threading isolation layer, and PyInstaller executable build tools:
      - main: Desktop application window and event loop
      - gui_wrapper: Process-isolated translation worker
      - build_exe: Standalone executable packaging
===============================================================================
"""

from __future__ import annotations

from typing import Any

from backend.desktop.gui_wrapper import run_translation_process

try:
    from backend.desktop.main import App
except ImportError:
    App: Any = None

__all__: list[str] = [
    "App",
    "run_translation_process",
]
