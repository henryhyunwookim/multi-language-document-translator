"""
===============================================================================
Digital Text PDF Document Handler Module
===============================================================================

Purpose:
    Processes selectable, digital vector text PDF documents. Extracts bounding
    boxes for all text blocks, translates unique textual segments, redacts
    original glyphs, and inserts translated text with auto-fitting font sizes.
    Detects scanned or raster-only PDFs lacking digital text layers and seamlessly
    delegates them to ScannedPdfHandler for Multimodal Vision translation.

Usage:
    from backend.handlers.pdf_digital import DigitalPdfHandler

    handler = DigitalPdfHandler(translator)
    output_pdf_stream = handler.process(input_pdf_file)

===============================================================================
"""
from __future__ import annotations

import io
import re
from typing import Any, BinaryIO, Union

import fitz

from backend.engines.visual_inspector import inspect_visual_layout_cues
from backend.handlers.base_handler import BaseDocumentHandler


# =============================================================================
# DIGITAL VECTOR PDF HANDLER CLASS
# =============================================================================

class DigitalPdfHandler(BaseDocumentHandler):
    """
    Handler for native digital text PDF files utilizing early visual inspection,
    span-level mixed style preservation, vector redaction, and multi-format text rendering.
    """

    @staticmethod
    def _rgb_int_to_tuple(color_val: int) -> tuple[float, float, float]:
        """Converts integer color into PyMuPDF float RGB tuple (0.0 to 1.0)."""
        r = ((color_val >> 16) & 255) / 255.0
        g = ((color_val >> 8) & 255) / 255.0
        b = (color_val & 255) / 255.0
        return (r, g, b)

    @staticmethod
    def _rgb_int_to_hex(color_val: int) -> str:
        """Converts integer color into hex string (#RRGGBB)."""
        return f"#{color_val & 0xFFFFFF:06x}"

    @staticmethod
    def _parse_tagged_html(tagged_text: str, default_font_stack: str) -> str:
        """Converts tagged translation markup into PyMuPDF-compatible HTML for insert_htmlbox."""
        html = tagged_text.replace("\n", "<br/>")
        pattern = re.compile(r'<span\s+([^>]+)>(.*?)</span>', re.DOTALL)

        def _replace_tag(m):
            attrs_str = m.group(1)
            content = m.group(2)
            styles = []
            color_m = re.search(r'color=["\'](#?[0-9a-fA-F]{6})["\']', attrs_str)
            if color_m:
                styles.append(f"color: {color_m.group(1)};")
            size_m = re.search(r'size=["\']([0-9.]+)["\']', attrs_str)
            if size_m:
                styles.append(f"font-size: {size_m.group(1)}pt;")
            bold_m = re.search(r'bold=["\'](true|1)["\']', attrs_str, re.IGNORECASE)
            if bold_m:
                styles.append("font-weight: bold;")
            style_attr = f' style="{" ".join(styles)}"' if styles else ""
            return f"<span{style_attr}>{content}</span>"

        styled_html = pattern.sub(_replace_tag, html)
        return f"<div style=\"font-family: {default_font_stack}; line-height: 1.35;\">{styled_html}</div>"

    @staticmethod
    def _strip_tags(text: str) -> str:
        """Strips XML style tags to plain text for fallback rendering."""
        return re.sub(r'<[^>]+>', '', text)

    def process(self, input_file: Union[BinaryIO, bytes, io.BytesIO, Any], **kwargs: Any) -> io.BytesIO:
        """
        Executes digital PDF translation pipeline:
          Step 1: Early Visual Inspection of document pages
          Step 2: Span-level extraction preserving font size, color, and mixed formatting
          Step 3: Fallback check for scanned documents
          Step 4: Tone analysis and style-tag-aware translation
          Step 5: Vector redaction and high-fidelity rendering (htmlbox / auto-fit fallback)
        """
        self.check_cancelled()
        self.log("Loading PDF document...", stage="INIT", progress=5)
        raw_data = input_file.read() if hasattr(input_file, "read") else input_file
        doc = fitz.open(stream=raw_data, filetype="pdf")

        # ---------------------------------------------------------------------
        # Step 1: Early Visual Inspection
        # ---------------------------------------------------------------------
        self.check_cancelled()
        model_inst = getattr(self.translator, "model", None)
        if len(doc) > 0 and model_inst:
            try:
                self.log("Performing early visual inspection of original document layout...", stage="INIT", progress=10)
                first_page = doc[0]
                pix = first_page.get_pixmap(dpi=150)
                visual_cues = inspect_visual_layout_cues(pix.tobytes("png"), model_inst)
                self.log(
                    f"Visual Inspection: Layout={visual_cues.get('layout_type', 'unknown')}, "
                    f"MixedFormatting={visual_cues.get('has_mixed_formatting', False)}, "
                    f"Colors={visual_cues.get('dominant_colors', [])[:3]}",
                    stage="INIT",
                    progress=12,
                )
            except Exception as v_err:
                self.log(f"Visual inspection note: {v_err}", stage="INIT")

        # ---------------------------------------------------------------------
        # Step 2: Fine-Grained Span Extraction & Mixed Formatting Modeling
        # ---------------------------------------------------------------------
        self.check_cancelled()
        self.log("Extracting text and span styling from PDF pages...", stage="EXTRACT", progress=15)
        unique_texts: set[str] = set()
        sections: list[dict[str, Any]] = []
        # Item: (page_idx, rect, original_clean_text, tagged_input_text, primary_size, primary_color_tuple, is_mixed)
        page_blocks: list[tuple[int, fitz.Rect, str, str, float, tuple[float, float, float], bool]] = []
        total_text_chars = 0

        for page_idx, page in enumerate(doc):
            self.check_cancelled()
            page_texts: list[str] = []
            page_dict = page.get_text("dict")

            for b in page_dict.get("blocks", []):
                if b.get("type") == 0:  # Text block
                    bbox = b.get("bbox", (0, 0, 0, 0))
                    rect = fitz.Rect(bbox[0], bbox[1], bbox[2], bbox[3])
                    spans_data = []

                    for line in b.get("lines", []):
                        for s in line.get("spans", []):
                            txt = s.get("text", "")
                            if txt.strip():
                                spans_data.append({
                                    "text": txt,
                                    "size": s.get("size", 11.0),
                                    "color": s.get("color", 0),
                                    "bold": bool(s.get("flags", 0) & 16),
                                    "italic": bool(s.get("flags", 0) & 2),
                                })

                    if not spans_data:
                        continue

                    # Plain clean text across the block
                    full_plain_text = " ".join(s["text"].strip() for s in spans_data if s["text"].strip()).strip()
                    if not full_plain_text:
                        continue

                    # Check for mixed formatting (different colors, sizes, or weights)
                    first_color = spans_data[0]["color"]
                    first_size = spans_data[0]["size"]
                    first_bold = spans_data[0]["bold"]
                    has_mixed = any(
                        s["color"] != first_color or abs(s["size"] - first_size) > 1.0 or s["bold"] != first_bold
                        for s in spans_data
                    )

                    primary_size = float(first_size)
                    primary_color = self._rgb_int_to_tuple(first_color)

                    if has_mixed:
                        # Construct tagged representation
                        tagged_parts = []
                        for s in spans_data:
                            hex_c = self._rgb_int_to_hex(s["color"])
                            sz = s["size"]
                            b_flag = s["bold"]
                            t = s["text"]
                            tagged_parts.append(f'<span color="{hex_c}" size="{sz:.1f}" bold="{b_flag}">{t}</span>')
                        tagged_text = "".join(tagged_parts)
                        target_trans_text = tagged_text
                    else:
                        target_trans_text = full_plain_text

                    page_texts.append(target_trans_text)
                    unique_texts.add(target_trans_text)
                    total_text_chars += len(full_plain_text)
                    page_blocks.append((page_idx, rect, full_plain_text, target_trans_text, primary_size, primary_color, has_mixed))

            sections.append({
                "name": f"Page {page_idx + 1}",
                "texts": page_texts,
                "tone": getattr(self.translator, "overall_tone", "formal"),
            })

        self.log(
            f"Extracted {len(unique_texts)} unique text blocks ({total_text_chars} total characters) across {len(doc)} pages.",
            stage="EXTRACT",
            progress=25,
        )

        # ---------------------------------------------------------------------
        # Step 3: Fallback Check for Non-Digital/Scanned PDFs
        # ---------------------------------------------------------------------
        if total_text_chars < 20 or len(unique_texts) == 0:
            self.log(
                "No digital text layer found in PDF (scanned image document). Switching to Multimodal Vision translation...",
                stage="EXTRACT",
                progress=30,
            )
            from backend.handlers.pdf_scanned import ScannedPdfHandler
            scanned_handler = ScannedPdfHandler(self.translator)
            return scanned_handler.process_doc(doc)

        # ---------------------------------------------------------------------
        # Step 4: Tone Analysis & Style-Tag-Aware Translation
        # ---------------------------------------------------------------------
        self.check_cancelled()
        translation_dict: dict[str, str] = {}
        if unique_texts:
            self.log("Analyzing document tone...", stage="TRANSLATE", progress=35)
            if hasattr(self.translator, "_analyze_tones"):
                self.translator.sections = sections
                self.translator._analyze_tones()

            self.check_cancelled()
            self.log("Starting translation with style and formatting tags...", stage="TRANSLATE", progress=45)
            translation_dict = self.translator._translate_texts(list(unique_texts))
            self.log("Translation complete.", stage="TRANSLATE", progress=75)
        else:
            self.log("No extractable text found in PDF.")

        # ---------------------------------------------------------------------
        # Step 5: Redaction & High-Fidelity Text Insertion
        # ---------------------------------------------------------------------
        self.check_cancelled()
        self.log("Applying translations and preserved formatting to PDF...", stage="RENDER", progress=85)

        target_lower = getattr(self.translator, "target_lang", "English").lower()
        if "japan" in target_lower:
            fontname = "japan"
            font_stack = "'Hiragino Sans', 'Yu Gothic', 'Noto Sans CJK JP', sans-serif"
        elif "chin" in target_lower:
            fontname = "china-s"
            font_stack = "'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif"
        elif "korea" in target_lower:
            fontname = "korea"
            font_stack = "'Malgun Gothic', 'Noto Sans CJK KR', sans-serif"
        else:
            fontname = "helv"
            font_stack = "Helvetica, Arial, sans-serif"

        for page_idx, page in enumerate(doc):
            self.check_cancelled()
            blocks_for_page = [item for item in page_blocks if item[0] == page_idx]
            if not blocks_for_page:
                continue

            # Stage 5a: Redact original bounding boxes
            for _, rect, _, _, _, _, _ in blocks_for_page:
                page.add_redact_annot(rect, fill=(1, 1, 1))

            page.apply_redactions()

            # Stage 5b: Precision insertion
            for _, rect, full_plain, target_input, prim_sz, prim_color, is_mixed in blocks_for_page:
                translated_raw = translation_dict.get(target_input) or translation_dict.get(full_plain)
                if not translated_raw:
                    continue

                if is_mixed or "<span" in translated_raw:
                    # Render via HTML Box with preserved colors, sizes, and weights
                    html_content = self._parse_tagged_html(translated_raw, font_stack)
                    rc = page.insert_htmlbox(rect, html_content, scale_low=0.35)
                    # If htmlbox succeeded (returned tuple with scale)
                    if isinstance(rc, (tuple, list)):
                        continue

                # Clean plain text fallback
                clean_text = self._strip_tags(translated_raw)
                start_sz = min(max(int(prim_sz), 8), int(rect.height * 0.8)) if prim_sz > 0 else 11
                fitted = False
                for sz in range(start_sz, 4, -1):
                    rc = page.insert_textbox(rect, clean_text, fontname=fontname, fontsize=sz, color=prim_color)
                    if rc >= 0:
                        fitted = True
                        break
                if not fitted:
                    page.insert_textbox(rect, clean_text, fontname=fontname, fontsize=5, color=prim_color)

        output = io.BytesIO()
        output.write(doc.write())
        output.seek(0)
        self.log("Processing finished.", stage="COMPLETE", progress=100)
        return output

