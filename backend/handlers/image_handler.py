"""
===============================================================================
Standalone Image Document Handler Module
===============================================================================

Purpose:
    Processes standalone bitmap images (PNG, JPG, JPEG, WEBP) using Gemini
    Multimodal Vision. Formulates layout-aware prompts injecting universal
    document formatting and language-pair rules, outputting clean structured
    Markdown representations of tables, headings, seals, and body prose.

Usage:
    from backend.handlers.image_handler import ImageDocumentHandler

    handler = ImageDocumentHandler(translator)
    output_md_stream = handler.process(input_image_file, ext=".png")

===============================================================================
"""

from __future__ import annotations

import io
import json
from typing import Any, BinaryIO, Union

from backend.handlers.base_handler import BaseDocumentHandler
from backend.rules.document_rules import get_combined_rules


# =============================================================================
# IMAGE DOCUMENT HANDLER CLASS
# =============================================================================

class ImageDocumentHandler(BaseDocumentHandler):
    """
    Handler for standalone image files utilizing Gemini Multimodal Vision.
    """

    def process(
        self,
        input_file: Union[BinaryIO, bytes, io.BytesIO, Any],
        ext: str = ".png",
        **kwargs: Any,
    ) -> io.BytesIO:
        """
        Executes image translation pipeline:
          Step 1: Resolve MIME type and ingest binary image payload
          Step 2: Formulate prompt combining universal document rules & language pair rules
          Step 3: Call Gemini Multimodal Vision API and serialize translated Markdown

        Args:
            input_file: Raw file-like stream or binary bytes buffer.
            ext (str): File extension including dot (e.g. '.png', '.jpg', '.webp').
            **kwargs: Additional configuration parameters.

        Returns:
            io.BytesIO: Seek-zero positioned stream containing translated Markdown UTF-8 bytes.
        """
        self.check_cancelled()
        self.log(f"Processing image document ({ext})...", stage="INIT", progress=10)

        # ---------------------------------------------------------------------
        # Step 1: MIME Type Resolution & Image Buffer Ingestion
        # ---------------------------------------------------------------------
        image_data = input_file.read() if hasattr(input_file, "read") else input_file
        mime_type = "image/png"
        ext_lower = ext.lower()
        if ext_lower in [".jpg", ".jpeg"]:
            mime_type = "image/jpeg"
        elif ext_lower == ".webp":
            mime_type = "image/webp"

        # ---------------------------------------------------------------------
        # Step 2: Prompt Formulation with Universal Rules
        # ---------------------------------------------------------------------
        target_lang = getattr(self.translator, "target_lang", "English")
        combined_rules = get_combined_rules(target_lang=target_lang)

        prompt = f"""You are an expert document translator.
Translate all text in this image accurately and formally into {target_lang}.

{combined_rules}

Component inventory (untrusted layout evidence):
{json.dumps(getattr(self.translator, 'component_inventory', []))}

CRITICAL:
- Reconstruct the layout, tables, bullet items, and hierarchy faithfully.
- Keep every clause and line distinct; do not collapse lines into paragraphs.
- Output ONLY the translated Markdown.
"""

        # ---------------------------------------------------------------------
        # Step 3: Multimodal Vision API Inference & Serialization
        # ---------------------------------------------------------------------
        self.check_cancelled()
        self.log("Running Multimodal Vision translation...", stage="TRANSLATE", progress=40)

        response = self.translator.model.generate_content(
            [
                {"mime_type": mime_type, "data": image_data},
                prompt,
            ],
            request_options={"timeout": 90},
        )

        translated_content = response.text.strip() if response and response.text else ""

        output = io.BytesIO()
        output.write(translated_content.encode("utf-8"))
        output.seek(0)
        self.log("Image processing finished.", stage="COMPLETE", progress=100)
        return output
