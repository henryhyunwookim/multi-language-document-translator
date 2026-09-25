"""Native Word reconstruction with protected Office package parts."""
from backend.handlers.base_handler import BaseDocumentHandler
from backend.handlers.ooxml_text import translate_package


class DocxHandler(BaseDocumentHandler):
    def process(self, input_file, **kwargs):
        return translate_package(self.translator, input_file, "docx")