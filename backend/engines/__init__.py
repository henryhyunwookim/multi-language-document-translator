"""
===============================================================================
Document Engines Subpackage
===============================================================================

Purpose:
    Exposes document layout typesetting, review/audit, pipeline routing,
    and core translation engines:
      - translator: BaseTranslator, GeminiTranslator, GoogleTransTranslator
      - document_pipeline: Input pre-assessment and execution phase router
      - layout_engine: Universal typesetting, Markdown-to-HTML rendering, and CSS
      - review_engine: Multi-page sliding-window quality and numbering audit
===============================================================================
"""

from __future__ import annotations

from backend.engines.document_pipeline import InputAssessment, assess_input_data
from backend.engines.layout_engine import build_document_css, render_markdown_to_html
from backend.engines.review_engine import DocumentReviewEngine
from backend.engines.translator import (
    BaseTranslator,
    GeminiTranslator,
    GoogleTransTranslator,
)

__all__: list[str] = [
    "BaseTranslator",
    "GeminiTranslator",
    "GoogleTransTranslator",
    "InputAssessment",
    "assess_input_data",
    "build_document_css",
    "render_markdown_to_html",
    "DocumentReviewEngine",
]
