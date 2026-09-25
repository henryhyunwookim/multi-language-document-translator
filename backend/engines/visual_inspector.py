"""
===============================================================================
Document Visual Inspection & Layout Intelligence Module
===============================================================================

Purpose:
    Performs early visual inspection on original document pages, slides, or
    tables before textual extraction and translation.
    Detects:
      - Dominant brand/theme colors and highlight terms
      - Mixed-formatting density (multi-colored tokens, mixed font weights/sizes)
      - Visual layout types (presentation slide, dense report, matrix table)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def inspect_visual_layout_cues(
    image_bytes: bytes,
    model: Any,
    timeout: int = 15,
) -> dict[str, Any]:
    """
    Performs visual inspection of a rendered document page or slide bitmap.

    Args:
        image_bytes: PNG or JPEG image bytes of the original page/slide.
        model: Google GenerativeAI model instance (e.g. Gemini 3.8 Flash).
        timeout: Generation call timeout in seconds.

    Returns:
        dict: Inspection metadata containing dominant colors, mixed formatting presence,
              key highlighted terms, and structural layout classification.
    """
    if not image_bytes or not model:
        return {"has_mixed_formatting": True}

    prompt = """Analyze this document page/slide visually at the very first step before translation and return a clean JSON object with:
- "dominant_colors": list of hex color codes visible (e.g. ["#000000", "#CA0123", "#1F497D"])
- "has_mixed_formatting": boolean (true if headings or sentences have colored highlight terms, bold words mixed with regular text, or different font sizes in a single line/box)
- "primary_font_weight": string ("bold", "regular", or "mixed")
- "key_highlight_terms": list of visual words/numbers that are highlighted in distinct colors or styled badges
- "layout_type": string ("presentation_slide", "dense_text_report", "table_matrix", "form_checklist")

JSON:"""

    try:
        response = model.generate_content(
            [
                prompt,
                {"mime_type": "image/png", "data": image_bytes},
            ],
            generation_config={"response_mime_type": "application/json"},
            request_options={"timeout": timeout},
        )
        content = response.text.strip() if response and response.text else "{}"
        cues = json.loads(content)
        if isinstance(cues, dict):
            return cues
        return {"has_mixed_formatting": True}
    except Exception as exc:
        logger.warning(f"Visual inspection warning (proceeding with standard extraction): {exc}")
        return {"has_mixed_formatting": True, "error": str(exc)}
