"""
===============================================================================
Universal Multi-Language Document Translator - Backend Package
===============================================================================

Subpackages:
    - core     : Structured logging, configuration templates, and primitives.
    - desktop  : CustomTkinter GUI application, workers, and PyInstaller tooling.
    - engines  : Multimodal translation, layout rendering, and quality review.
    - handlers : Document format extractors/builders (PDF, Word, Excel, PPTX, Text).
    - rules    : Structural preservation rules, prompts, and tone profiles.
    - storage  : Model caching registry and cloud synchronization.

Entrypoints:
    - api.py  : FastAPI REST and Server-Sent Event (SSE) web service.
    - main.py : Desktop application launch point.
===============================================================================
"""

from __future__ import annotations

__version__ = "2.1.0"
