"""
===============================================================================
Document Pipeline Pre-Assessment and Routing Module
===============================================================================

Purpose:
    Analyzes incoming document payloads prior to translation execution.
    Determines the document category (kind) and predicts the sequential
    pipeline stages (e.g. OCR extraction, multimodal vision, layout reconstruction).

Usage:
    from backend.engines.document_pipeline import assess_input_data, InputAssessment

    assessment = assess_input_data(file_bytes, ".pdf")
    print(assessment.kind, assessment.processing_steps)

===============================================================================
"""

from __future__ import annotations

from dataclasses import dataclass


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass(frozen=True)
class InputAssessment:
    """
    Immutable representation of document classification and planned pipeline steps.

    Attributes:
        kind (str): Normalized file category (e.g. 'PDF', 'DOCX', 'XLSX', 'IMAGE').
        processing_steps (tuple[str, ...]): Sequential stages planned for execution.
    """
    kind: str
    processing_steps: tuple[str, ...]


# =============================================================================
# PIPELINE ROUTING & ASSESSMENT
# =============================================================================

def assess_input_data(input_data: bytes, extension: str) -> InputAssessment:
    """
    Describes the selected processing path before translation begins.

    Inspects file extension and payload metadata to formulate a clear
    roadmap of extraction, translation, and rendering operations.

    Args:
        input_data (bytes): Raw binary bytes of the input file.
        extension (str): File extension including or excluding dot (e.g. '.pdf', 'docx').

    Returns:
        InputAssessment: Assessment object specifying document kind and pipeline steps.
    """
    from backend.quality.inspection import inspect_document
    manifest = inspect_document(input_data, extension)
    normalized_extension = extension.lower().strip()
    ext_clean = normalized_extension.lstrip(".")

    # Pipeline step routing table by document extension
    step_map: dict[str, tuple[str, ...]] = {
        "pdf": (
            "Inspect digital vector text layer vs. scanned bitmap",
            "Extract text blocks or render 150 DPI page bitmaps",
            "Translate content with universal legal & layout fidelity rules",
            "Audit numbering continuity and page boundaries",
            "Typeset and compile publication-ready output PDF",
        ),
        "docx": (
            "Parse Word document structure (paragraphs, tables, runs)",
            "Extract unique text segments and analyze tone",
            "Translate segments via AI model",
            "Inject translated text preserving run formatting and table schemas",
        ),
        "pptx": (
            "Inspect slides, shapes, tables, and speaker notes",
            "Extract unique presentation text runs",
            "Translate presentation text with tone consistency",
            "Reconstruct slide elements with preserved layout geometry",
        ),
        "xlsx": (
            "Parse workbook sheets, cells, formulas, and headers",
            "Extract unique cell text entries",
            "Translate text preserving numerical formulas and styling",
            "Generate translated Excel workbook",
        ),
        "png": ("Ingest image bitmap", "Perform Gemini Multimodal Vision translation", "Render Markdown"),
        "jpg": ("Ingest image bitmap", "Perform Gemini Multimodal Vision translation", "Render Markdown"),
        "jpeg": ("Ingest image bitmap", "Perform Gemini Multimodal Vision translation", "Render Markdown"),
        "webp": ("Ingest image bitmap", "Perform Gemini Multimodal Vision translation", "Render Markdown"),
        "txt": ("Decode text stream", "Translate text blocks with tone alignment", "Encode output stream"),
        "md": ("Parse Markdown tokens", "Translate prose and tables", "Reconstruct Markdown syntax"),
        "csv": ("Parse tabular CSV rows", "Translate cells", "Format serialized CSV"),
        "json": ("Parse JSON structure", "Translate string values while preserving keys", "Serialize JSON"),
        "html": ("Parse HTML DOM", "Translate body text and attributes", "Serialize HTML DOM"),
    }

    kind_label = manifest.kind.upper()
    steps = step_map.get(ext_clean, (f"Translate {normalized_extension or 'file'}",))

    return InputAssessment(
        kind=kind_label,
        processing_steps=steps,
    )
