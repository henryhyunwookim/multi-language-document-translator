"""
===============================================================================
Document Handlers Package Initialization
===============================================================================

Purpose:
    Exposes all document-type specific handlers through a centralized interface.
    Separates document extraction and rendering logic from general translator
    orchestration and universal prompt rules.

Exported Classes:
    - BaseDocumentHandler : Abstract handler interface
    - ScannedPdfHandler   : Multimodal Vision scanned PDF processor
    - DigitalPdfHandler   : Vector text PDF processor with auto-fit replacement
    - DocxHandler         : Microsoft Word (.docx) processor
    - PptxHandler         : Microsoft PowerPoint (.pptx) processor
    - XlsxHandler         : Microsoft Excel (.xlsx) processor
    - TextDocumentHandler : Plain text, Markdown, CSV, JSON, HTML processor
    - ImageDocumentHandler: Standalone image Multimodal Vision processor
===============================================================================
"""

from __future__ import annotations

try:
    from backend.handlers.base_handler import BaseDocumentHandler
    from backend.handlers.pdf_scanned import ScannedPdfHandler
    from backend.handlers.pdf_digital import DigitalPdfHandler
    from backend.handlers.docx_handler import DocxHandler
    from backend.handlers.pptx_handler import PptxHandler
    from backend.handlers.xlsx_handler import XlsxHandler
    from backend.handlers.text_handler import TextDocumentHandler
    from backend.handlers.image_handler import ImageDocumentHandler
except ImportError:
    from .base_handler import BaseDocumentHandler
    from .pdf_scanned import ScannedPdfHandler
    from .pdf_digital import DigitalPdfHandler
    from .docx_handler import DocxHandler
    from .pptx_handler import PptxHandler
    from .xlsx_handler import XlsxHandler
    from .text_handler import TextDocumentHandler
    from .image_handler import ImageDocumentHandler

__all__: list[str] = [
    "BaseDocumentHandler",
    "ScannedPdfHandler",
    "DigitalPdfHandler",
    "DocxHandler",
    "PptxHandler",
    "XlsxHandler",
    "TextDocumentHandler",
    "ImageDocumentHandler",
]
