"""
===============================================================================
PyInstaller Standalone Executable Packaging Script
===============================================================================

Purpose:
    Packages the Desktop Document Translator application into a self-contained,
    single-file Windows executable (.exe) using PyInstaller. Bundles
    CustomTkinter themes and assets.

Usage:
    # Run from repository root:
    python backend/desktop/build_exe.py

Prerequisites & Dependencies:
    - Python 3.10+
    - PyInstaller (pip install pyinstaller)
    - CustomTkinter (pip install customtkinter)

Outputs:
    - dist/DocumentTranslator.exe
    - build/DocumentTranslator/
===============================================================================
"""

from __future__ import annotations

import os
import sys
from typing import NoReturn


# =============================================================================
# ENVIRONMENT & DEPENDENCY VALIDATION
# =============================================================================

def _validate_environment() -> str:
    """
    Validates required dependencies and returns the CustomTkinter asset directory.
    """
    try:
        import customtkinter
        ctk_path = os.path.dirname(customtkinter.__file__)
        return ctk_path
    except ImportError as err:
        sys.stderr.write(f"Error: customtkinter is not installed: {err}\n")
        sys.stderr.write("Run: pip install customtkinter\n")
        sys.exit(1)


# =============================================================================
# PYINSTALLER INVOCATION
# =============================================================================

def build_executable() -> None:
    """
    Assembles compilation arguments and triggers the PyInstaller build pipeline.
    """
    # Step 1: Validate dependencies and locate assets
    ctk_path = _validate_environment()

    # Step 2: Resolve entrypoint and directory paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    main_path = os.path.join(current_dir, "main.py")

    if not os.path.exists(main_path):
        sys.stderr.write(f"Error: Entrypoint not found at {main_path}\n")
        sys.exit(1)

    # Step 3: Configure build flags
    # --onefile: Bundle everything into a single standalone binary
    # --noconsole: Suppress background Windows console window
    # --clean: Clean cache before build
    # --add-data: Bundle CustomTkinter theme assets
    args: list[str] = [
        main_path,
        "--name=DocumentTranslator",
        "--onefile",
        "--noconsole",
        "--clean",
        f"--add-data={ctk_path}{os.pathsep}customtkinter",
    ]

    print("===================================================================")
    print("Building DocumentTranslator Standalone Executable with PyInstaller")
    print("===================================================================")
    print(f"Entrypoint: {main_path}")
    print(f"Asset Path: {ctk_path}")
    print("Build Arguments:", " ".join(args))
    print("===================================================================")

    try:
        import PyInstaller.__main__
        PyInstaller.__main__.run(args)
        print("\nBuild completed successfully. Check the 'dist/' folder for DocumentTranslator.exe.")
    except Exception as exc:
        sys.stderr.write(f"Build failed with exception: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    build_executable()
