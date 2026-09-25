"""
===============================================================================
Scanned & Image-Based PDF Document Handler Module
===============================================================================

Purpose:
    Handles non-digital, scanned, image-heavy, or layout-complex PDF documents.
    Renders pages to high-resolution bitmaps (150 DPI), translates pages via
    Gemini Multimodal Vision with universal legal, hierarchy, and line-break
    preservation rules, executes multi-page numbering and continuity auditing
    via DocumentReviewEngine, and typesets publication-grade output PDFs with
    PyMuPDF's HTML/CSS layout engine.

Usage:
    from backend.handlers.pdf_scanned import ScannedPdfHandler

    handler = ScannedPdfHandler(translator)
    output_pdf_stream = handler.process(input_pdf_file)

===============================================================================
"""

from __future__ import annotations

import io
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, BinaryIO, Optional, Union

import fitz

from backend.handlers.base_handler import BaseDocumentHandler
from backend.rules.document_rules import get_combined_rules
from backend.engines.layout_engine import render_markdown_to_html
from backend.engines.review_engine import DocumentReviewEngine
from backend.core.observability import init_langsmith
from backend.agents import run_page_agent_pipeline
import json
import os


# =============================================================================
# SCANNED PDF PROCESSOR CLASS
# =============================================================================

class ScannedPdfHandler(BaseDocumentHandler):
    """
    Multimodal Vision-based processor for image and scanned PDF documents.
    """

    def process(self, input_file: Union[BinaryIO, bytes, io.BytesIO, Any], **kwargs: Any) -> io.BytesIO:
        """
        Ingests a raw stream, bytearray, or fitz.Document and delegates to process_doc.

        Args:
            input_file: Raw file stream, byte buffer, or existing fitz.Document.
            **kwargs: Additional configuration parameters.

        Returns:
            io.BytesIO: Seek-zero positioned stream containing the reconstructed PDF.
        """
        raw_data = input_file.read() if hasattr(input_file, "read") else input_file
        doc = fitz.open(stream=raw_data, filetype="pdf") if isinstance(raw_data, (bytes, bytearray)) else input_file
        return self.process_doc(doc)

    def process_doc(self, doc: fitz.Document) -> io.BytesIO:
        """
        Executes the end-to-end multi-agent scanned document reconstruction pipeline:
          Step 1: Ingest and render pages to high-res PNG images (150 DPI)
          Step 2: Initialize LangSmith telemetry and agent configuration
          Step 3: Concurrently process pages through the LangGraph multi-agent pipeline
          Step 4: Audit numbering continuity and cross-references via DocumentReviewEngine
          Step 5: Typeset publication-ready output PDF using PyMuPDF HTML/CSS engine

        Args:
            doc (fitz.Document): PyMuPDF document instance.

        Returns:
            io.BytesIO: Reconstructed PDF byte stream.
        """
        total_pages = len(doc)
        raw_model = getattr(self.translator, "model_name", "gemini-3.8-flash")
        model_name = "gemini-2.5-flash" if (not raw_model or raw_model == "AI Vision") else raw_model
        target_lang = getattr(self.translator, "target_lang", "English")

        api_key = getattr(self.translator, "api_key", None) or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            try:
                from backend.core.cloud_secrets import get_gemini_api_key
                api_key = get_gemini_api_key()
            except Exception:
                pass

        # Initialize LangSmith observability
        init_langsmith()

        self.log(
            f"Starting LangGraph Multi-Agent Document Translation for {total_pages} pages using {model_name}...",
            stage="INIT",
            progress=5,
        )
        self.check_cancelled()

        # ---------------------------------------------------------------------
        # Step 1: Page Image Rendering & Multimodal Vision Ingestion
        # ---------------------------------------------------------------------
        page_images: list[tuple[int, bytes, float, float]] = []
        for idx, page in enumerate(doc):
            self.check_cancelled()
            pix = page.get_pixmap(dpi=150)
            page_images.append((idx, pix.tobytes("png"), page.rect.width, page.rect.height))

        self.log(
            f"Extracted {len(page_images)} page images at 150 DPI. Processing pages via Multi-Agent Graph...",
            stage="EXTRACT",
            progress=15,
        )

        translated_pages: dict[int, str] = {}
        page_quality = {}

        # ---------------------------------------------------------------------
        # Step 3: Concurrent Multi-Threaded Multi-Agent Page Translation with Sequenced Logging
        # ---------------------------------------------------------------------
        def translate_single_page(
            idx: int,
            img_bytes: bytes,
            p_width: float,
            p_height: float,
        ) -> tuple[int, str, list[tuple[str, str]]]:
            self.check_cancelled()
            local_logs: list[tuple[str, str]] = []
            max_retries = 4
            for attempt in range(max_retries):
                try:
                    self.check_cancelled()
                    res_state = run_page_agent_pipeline(
                        page_idx=idx,
                        image_bytes=img_bytes,
                        width=p_width,
                        height=p_height,
                        api_key=api_key or "",
                        target_lang=target_lang,
                        model_name=model_name,
                        model=self.translator.model,
                    )
                    text = res_state.get("draft_markdown", "")
                    if not text.strip() or text.startswith("*[Translation Error:"):
                        raise ValueError("Page translation is empty or contains an API error.")
                    page_quality[idx] = res_state
                    return idx, text, local_logs
                except Exception as exc:
                    err_str = str(exc).lower()
                    is_rate_limit = any(
                        k in err_str
                        for k in ["429", "resourceexhausted", "quota", "too many requests", "rate limit"]
                    )
                    if is_rate_limit and attempt < max_retries - 1:
                        # Exponential backoff with jitter: 8s, 16s, 32s, up to 60s
                        base_wait = min(60.0, (2 ** attempt) * 8.0)
                        wait_time = base_wait + random.uniform(1.0, 4.0)
                        local_logs.append((
                            f"Rate limit encountered on page {idx + 1}. Waiting {int(wait_time)}s before retry (attempt {attempt + 1}/{max_retries})...",
                            "TRANSLATE",
                        ))
                        time.sleep(wait_time)
                    elif attempt < max_retries - 1:
                        wait_time = 3.0 + random.uniform(0.5, 2.5)
                        local_logs.append((
                            f"Transient error on page {idx + 1} ({exc}). Retrying in {int(wait_time)}s (attempt {attempt + 1}/{max_retries})...",
                            "TRANSLATE",
                        ))
                        time.sleep(wait_time)
                    else:
                        local_logs.append((
                            f"Error translating page {idx + 1} after {max_retries} attempts: {exc}",
                            "ERROR",
                        ))
                        raise RuntimeError(f"Page {idx + 1} failed translation after retries") from exc
            return idx, "", local_logs

        workers = min(3, total_pages)
        page_buffer: dict[int, tuple[str, list[tuple[str, str]]]] = {}
        next_expected_page = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {}
            for idx, img_b, p_w, p_h in page_images:
                future_to_idx[executor.submit(translate_single_page, idx, img_b, p_w, p_h)] = idx
                time.sleep(0.2)  # Gentle submission pacing to avoid burst RPM spikes

            for future in as_completed(future_to_idx):
                self.check_cancelled()
                idx, text, p_logs = future.result()
                page_buffer[idx] = (text, p_logs)

                # Sequenced release: flush logs in strict monotonic ascending order (0, 1, 2...)
                while next_expected_page in page_buffer:
                    res_text, res_logs = page_buffer.pop(next_expected_page)
                    translated_pages[next_expected_page] = res_text

                    # Flush intermediate retry/error logs collected for this page
                    for msg, stg in res_logs:
                        self.log(msg, stage=stg)

                    pct = 15 + int(50 * (next_expected_page + 1) / total_pages)
                    self.log(
                        f"Page {next_expected_page + 1}/{total_pages} translated successfully.",
                        stage="TRANSLATE",
                        progress=pct,
                    )
                    next_expected_page += 1

        self.check_cancelled()

        # ---------------------------------------------------------------------
        # Step 4: Multi-Page Quality & Numbering Audit Review
        # ---------------------------------------------------------------------
        from backend.quality.models import QualityReport, Finding
        report = QualityReport(checks={"coverage": "passed", "page_review": "passed"})
        from backend.quality.models import Manifest
        report.manifest = Manifest('pdf', '')
        for page_idx, state in page_quality.items():
            report.manifest.components.extend({**item, 'part': f'page:{page_idx + 1}'}
                for item in state.get('layout_meta', {}).get('components', []))
            if state.get("quality_status") != "passed":
                report.checks["page_review"] = "needs_review"
                report.findings.append(Finding("page_review", state.get("critique") or state.get("translation_critique") or "Page review did not pass.", location=f"page:{page_idx + 1}"))
        self.translator.quality_report = report.finish()
        review_engine = DocumentReviewEngine(
            model=self.translator.model,
            target_lang=target_lang,
            log_callback=self.translator.log if hasattr(self.translator, "log") else None,
            check_cancelled=self.check_cancelled,
        )
        translated_pages = review_engine.review_pages(translated_pages, max_review_loops=2)

        # ---------------------------------------------------------------------
        # Step 5: Typesetting & Publication PDF Compilation
        # ---------------------------------------------------------------------
        self.log("Typesetting output PDF document with PyMuPDF...", stage="RENDER", progress=88)
        self.check_cancelled()

        out_doc = fitz.open()

        for idx, _, p_width, p_height in page_images:
            self.check_cancelled()
            md_content = translated_pages.get(idx, "")

            from backend.quality.pdf_rendering import checked_markdown_page
            from backend.quality.models import QualityFailure
            try:
                rendered, findings = checked_markdown_page(md_content, p_width, p_height, target_lang)
                with fitz.open(stream=rendered, filetype="pdf") as rendered_page:
                    out_doc.insert_pdf(rendered_page)
                for finding in findings:
                    finding.location = f"page:{idx + 1}"
                report.findings.extend(findings)
            except ValueError as exc:
                report.checks["rendered_content"] = "failed"
                report.findings.append(Finding("page_render_failed", str(exc), "error", location=f"page:{idx + 1}"))
                self.translator.quality_report = report.finish()
                raise QualityFailure(report) from exc

        out_buffer = io.BytesIO()
        report.checks["rendered_content"] = "passed"
        self.translator.quality_report = report.finish()
        out_buffer.write(out_doc.write(garbage=4, deflate=True))
        out_buffer.seek(0)
        self.log(
            f"Scanned PDF processing complete! Output document has {len(out_doc)} pages ({len(out_buffer.getvalue())} bytes).",
            stage="COMPLETE",
            progress=100,
        )
        return out_buffer
