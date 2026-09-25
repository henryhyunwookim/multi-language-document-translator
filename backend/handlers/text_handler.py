"""
===============================================================================
Text, Markdown, CSV, JSON, and HTML Document Handler Module
===============================================================================

Purpose:
    Processes structured and unstructured textual file formats:
      - Plain Text (.txt)
      - Markdown (.md)
      - Comma-Separated Values (.csv)
      - JavaScript Object Notation (.json)
      - HyperText Markup Language (.html, .htm)
    Dispatches to format-preserving translation methods ensuring syntax,
    key names, markup tags, and CSV columns remain uncorrupted.

Usage:
    from backend.handlers.text_handler import TextDocumentHandler

    handler = TextDocumentHandler(translator)
    output_stream = handler.process(input_file, doc_type="markdown")

===============================================================================
"""

from __future__ import annotations

import io
from typing import Any, BinaryIO, Union

from backend.handlers.base_handler import BaseDocumentHandler


# =============================================================================
# TEXT & STRUCTURED DOCUMENT HANDLER CLASS
# =============================================================================

class TextDocumentHandler(BaseDocumentHandler):
    """
    Handler for text-based and structured serialized file formats.
    """

    def process_plain_text(self, input_file: Union[BinaryIO, bytes, io.BytesIO, Any]) -> io.BytesIO:
        """
        Translates raw unstructured plain text preserving paragraph breaks.

        Args:
            input_file: Raw file-like stream or bytes buffer.

        Returns:
            io.BytesIO: Seek-zero positioned stream containing translated UTF-8 text bytes.
        """
        self.check_cancelled()
        self.log("Loading text file...", stage="INIT", progress=5)
        raw_data = input_file.read() if hasattr(input_file, "read") else input_file
        text = raw_data.decode("utf-8") if isinstance(raw_data, (bytes, bytearray)) else str(raw_data)

        self.check_cancelled()
        self.log("Translating text...", stage="TRANSLATE", progress=30)
        translated = self.translator.translate_text(text)

        output = io.BytesIO()
        output.write(translated.encode("utf-8"))
        output.seek(0)
        self.log("Text processing finished.", stage="COMPLETE", progress=100)
        return output

    def process(
        self,
        input_file: Union[BinaryIO, bytes, io.BytesIO, Any],
        doc_type: str = "text",
        **kwargs: Any,
    ) -> io.BytesIO:
        """
        Dispatches input file to format-specific handler logic based on doc_type.

        Args:
            input_file: Raw file stream or bytes buffer.
            doc_type (str): Format specifier ('text', 'markdown', 'csv', 'json', 'html').
            **kwargs: Additional options passed to internal processors.

        Returns:
            io.BytesIO: Translated document byte stream.
        """
        doc_lower = doc_type.lower()
        if doc_lower == "text":
            return self.process_plain_text(input_file)
        elif doc_lower == "markdown":
            return self.translator.process_markdown(input_file)
        elif doc_lower == "csv":
            return self.translator.process_csv(input_file)
        elif doc_lower == "json":
            return self.translator.process_json(input_file)
        elif doc_lower == "html":
            return self.translator.process_html(input_file)
        return self.process_plain_text(input_file)
