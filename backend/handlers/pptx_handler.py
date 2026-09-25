"""Office text translation preserving original package parts."""
import io
from typing import Any

from backend.handlers.base_handler import BaseDocumentHandler
from backend.handlers.ooxml_text import translate_package


class PptxHandler(BaseDocumentHandler):
    def process(self, input_file: Any, **kwargs: Any) -> io.BytesIO:
        return translate_package(self.translator, input_file, "pptx")
