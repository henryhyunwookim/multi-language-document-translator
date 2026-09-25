import io
import csv
import re
import os
import time
import copy
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from google import genai as _genai
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from abc import ABC, abstractmethod
import openpyxl
try:
    from googletrans import Translator
except ImportError:
    Translator = None
import json
import html
from html.parser import HTMLParser
import fitz # PyMuPDF
import docx
import markdown
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

try:
    from backend.rules.prompt_templates import get_rules
except ImportError:
    try:
        from backend.prompt_templates import get_rules
    except ImportError:
        try:
            from .prompt_templates import get_rules
        except ImportError:
            from prompt_templates import get_rules

try:
    from backend.core.logger_config import setup_logging
except ImportError:
    try:
        from backend.logger_config import setup_logging
    except ImportError:
        from logger_config import setup_logging

logger = setup_logging("translator")


class BaseTranslator(ABC):
    def __init__(self, target_lang: str = 'Japanese', log_callback=None, stop_event=None):
        self.target_lang = target_lang
        self.source_lang = "Auto-detect"
        self.translation_dict = {}
        self.sections = [] # List of {"name": str, "texts": [str], "tone": str}
        self.overall_tone = "business professional" # Default
        self.log_callback = log_callback
        self.stop_event = stop_event
        self.quality_enabled = True
        self.quality_report = None
        self.glossary = {}

    def log(self, message: str, stage: str = "INFO", progress: int = None):
        """
        Logs a message with stage categorization and optional progress percentage.
        Sends structured event to log_callback and writes to standard logger.
        """
        logger.info(f"[{stage}] {message}")
        if self.log_callback:
            event = {
                "stage": stage,
                "message": message,
                "progress": progress,
                "timestamp": time.strftime("%H:%M:%S")
            }
            try:
                self.log_callback(event)
            except TypeError:
                try:
                    self.log_callback(message, stage=stage, progress=progress)
                except TypeError:
                    self.log_callback(f"[{stage}] {message}")
        else:
            print(f"[{stage}] {message}")
            
    def check_cancelled(self):
        if self.stop_event and self.stop_event.is_set():
            self.log("Cancellation requested.")
            raise InterruptedError("Process cancelled by user.")

    def process_presentation(self, input_file) -> io.BytesIO:
        """Translate text while preserving the original presentation package."""
        from backend.handlers.pptx_handler import PptxHandler
        return PptxHandler(self).process(input_file)

    def process_excel(self, input_file) -> io.BytesIO:
        """Translate text while preserving drawings, formulas and embedded objects."""
        from backend.handlers.xlsx_handler import XlsxHandler
        return XlsxHandler(self).process(input_file)

    def process_text(self, input_file) -> io.BytesIO:
        """
        Processes a plain text file (file-like object) and returns the translated text as a BytesIO object.
        """
        self.check_cancelled()
        self.log("Reading text file...")
        content = input_file.read().decode('utf-8', errors='ignore')

        self.check_cancelled()
        self.log("Extracting text...")
        unique_texts = self._extract_unique_texts_text(content)
        self.log(f"Found {len(unique_texts)} unique text chunks (lines).")

        self.check_cancelled()
        self.log("Analyzing tone...")
        self._analyze_tones()

        self.check_cancelled()
        if unique_texts:
            self.log("Starting translation...")
            self.translation_dict = self._translate_texts(unique_texts)
            self.log("Translation complete.")
        else:
            self.log("No text found to translate.")

        self.check_cancelled()
        self.log("Applying translations...")
        translated_content = self._replace_text_in_text(content)

        output = io.BytesIO()
        output.write(translated_content.encode('utf-8'))
        output.seek(0)
        self.log("Processing finished.")
        return output

    def process_docx(self, input_file) -> io.BytesIO:
        """Patch Word text with protected links, fields and quality gates."""
        from backend.handlers.ooxml_text import translate_package
        return translate_package(self, input_file, "docx")

    @abstractmethod
    def translate_text(self, text: str) -> str:
        """
        Translates a single block of text.
        """
        pass

    @abstractmethod
    def _translate_texts(self, texts: list) -> dict:
        """
        Abstract method to translate a list of texts.
        Must return a dictionary {original_text: translated_text}.
        """
        pass

    def _analyze_tones(self):
        """
        Analyzes the tone of the entire document and each section.
        Subclasses like GeminiTranslator should implement this.
        """
        pass

    def _iter_shapes(self, prs):
        """Iterator to yield all shapes in the presentation"""
        for slide in prs.slides:
            for shape in slide.shapes:
                yield shape

    def _iter_text_containing_shapes(self, shape):
        """Recursively yield shapes that can contain text"""
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            for subshape in shape.shapes:
                yield from self._iter_text_containing_shapes(subshape)
        elif shape.has_text_frame:
            yield shape
        elif shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    yield cell

    def _extract_unique_texts(self, prs) -> list:
        unique_texts = set()
        self.sections = []
        for i, slide in enumerate(prs.slides):
            slide_texts = []
            for shape in slide.shapes:
                for text_shape in self._iter_text_containing_shapes(shape):
                    if not hasattr(text_shape, 'text_frame') or not text_shape.text_frame:
                        continue
                    for paragraph in text_shape.text_frame.paragraphs:
                        text = paragraph.text.strip()
                        if text:
                            unique_texts.add(text)
                            slide_texts.append(text)
            self.sections.append({
                "name": f"Slide {i+1}",
                "texts": slide_texts,
                "tone": "unknown"
            })
        return list(unique_texts)

    def _replace_text_in_presentation(self, prs):
        count = 0
        for shape in self._iter_shapes(prs):
            for text_shape in self._iter_text_containing_shapes(shape):
                if not text_shape.text_frame:
                    continue
                for paragraph in text_shape.text_frame.paragraphs:
                    original_text = paragraph.text.strip()
                    if original_text in self.translation_dict:
                        translated_text = self.translation_dict[original_text]
                        if translated_text and translated_text != original_text:
                            self._apply_translation_preserving_format(paragraph, translated_text)
                            count += 1
        self.log(f"Replaced {count} text instances.")

    def _apply_translation_preserving_format(self, paragraph, new_text):
        # Capture baseline formatting from the first run
        font_name = None
        font_size = None
        font_bold = None
        font_italic = None
        font_color_rgb = None
        font_color_theme = None
        
        if paragraph.runs:
            r = paragraph.runs[0]
            font_name = r.font.name
            font_size = r.font.size
            font_bold = r.font.bold
            font_italic = r.font.italic
            try:
                if r.font.color.type == 1: # RGB
                    font_color_rgb = r.font.color.rgb
                elif r.font.color.type == 2: # THEME
                    font_color_theme = r.font.color.theme_color
            except:
                pass

        paragraph.clear()

        # Handle tagged mixed-formatting spans: <span color="..." size="..." bold="...">...</span>
        if "<span" in new_text:
            pattern = re.compile(r'<span\s+([^>]+)>(.*?)</span>', re.DOTALL)
            last_idx = 0
            from pptx.dml.color import RGBColor
            from pptx.util import Pt

            for match in pattern.finditer(new_text):
                start, end = match.span()
                if start > last_idx:
                    pre_text = new_text[last_idx:start]
                    if pre_text:
                        r = paragraph.add_run()
                        r.text = pre_text
                        if font_name: r.font.name = font_name
                        if font_size: r.font.size = font_size
                        if font_bold is not None: r.font.bold = font_bold
                        if font_italic is not None: r.font.italic = font_italic
                        if font_color_rgb: r.font.color.rgb = font_color_rgb
                        elif font_color_theme: r.font.color.theme_color = font_color_theme

                attrs_str = match.group(1)
                inner_text = match.group(2)
                r = paragraph.add_run()
                r.text = inner_text
                if font_name: r.font.name = font_name
                if font_size: r.font.size = font_size
                if font_bold is not None: r.font.bold = font_bold
                if font_italic is not None: r.font.italic = font_italic
                if font_color_rgb: r.font.color.rgb = font_color_rgb
                elif font_color_theme: r.font.color.theme_color = font_color_theme

                # Override with span-specific formatting
                cm = re.search(r'color=["\']#?([0-9a-fA-F]{6})["\']', attrs_str)
                if cm:
                    h = cm.group(1)
                    r.font.color.rgb = RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

                sm = re.search(r'size=["\']([0-9.]+)["\']', attrs_str)
                if sm:
                    try: r.font.size = Pt(float(sm.group(1)))
                    except: pass

                bm = re.search(r'bold=["\'](true|1)["\']', attrs_str, re.IGNORECASE)
                if bm:
                    r.font.bold = True
                elif re.search(r'bold=["\'](false|0)["\']', attrs_str, re.IGNORECASE):
                    r.font.bold = False

                last_idx = end

            if last_idx < len(new_text):
                post_text = new_text[last_idx:]
                if post_text:
                    r = paragraph.add_run()
                    r.text = post_text
                    if font_name: r.font.name = font_name
                    if font_size: r.font.size = font_size
                    if font_bold is not None: r.font.bold = font_bold
                    if font_italic is not None: r.font.italic = font_italic
                    if font_color_rgb: r.font.color.rgb = font_color_rgb
                    elif font_color_theme: r.font.color.theme_color = font_color_theme
            return

        # Single run fallback
        new_run = paragraph.add_run()
        new_run.text = new_text
        
        if font_name: new_run.font.name = font_name
        if font_size: new_run.font.size = font_size
        if font_bold is not None: new_run.font.bold = font_bold
        if font_italic is not None: new_run.font.italic = font_italic
        
        if font_color_rgb:
            new_run.font.color.rgb = font_color_rgb
        elif font_color_theme:
            new_run.font.color.theme_color = font_color_theme

    def _extract_unique_texts_excel(self, wb) -> list:
        unique_texts = set()
        self.sections = []
        for sheet in wb.worksheets:
            sheet_texts = []
            
            # Extract Sheet Title
            if sheet.title:
                unique_texts.add(sheet.title)
                sheet_texts.append(sheet.title)

            for row in sheet.iter_rows():
                for cell in row:
                    # Extract Cell Value
                    if cell.value and isinstance(cell.value, str):
                        text = cell.value.strip()
                        if text:
                            unique_texts.add(text)
                            sheet_texts.append(text)
                    
                    # Extract Cell Comment (Memo)
                    if cell.comment and cell.comment.text:
                        comment_text = cell.comment.text.strip()
                        if comment_text:
                            unique_texts.add(comment_text)
                            sheet_texts.append(comment_text)

            self.sections.append({
                "name": f"Sheet: {sheet.title}",
                "texts": sheet_texts,
                "tone": "unknown"
            })
        return list(unique_texts)

    def translate_text(self, text: str) -> str:
        """
        Translates a single block of text using the Three-Task Sequence.
        """
        if not text.strip():
            return ""
            
        self.check_cancelled()
        
        # Determine source language if not already known
        if not self.source_lang or self.source_lang == "Unknown":
            # Quick detection/tone check for the single text
            self.sections = [{"name": "Single Text", "texts": [text], "tone": "unknown"}]
            self._analyze_tones()

        rules = get_rules(self.source_lang, self.target_lang)
        
        prompt = f"""You have three tasks to complete in sequence. 
You only need to output the final result, which is the naturalized translation from {self.source_lang} to {self.target_lang}.

**Overall Document Context:**
- Source Language: {self.source_lang}
- Target Language: {self.target_lang}
- Overall Tone: {self.overall_tone}

--------------------------------------------------------------------------------------------------------------------

1. First task (Rule Application)
Apply the following specialized translation rules for {self.source_lang} to {self.target_lang} translation:

**
{rules}
**

--------------------------------------------------------------------------------------------------------------------

2. Second task (Translation)
Translate the text provided from {self.source_lang} to {self.target_lang}, using the rules from the first task.

--------------------------------------------------------------------------------------------------------------------

3. Third task (Naturalization)
Make sure the translated text sounds natural as if it were originally written in {self.target_lang}. 
Return ONLY the final naturalized translation. Do not include any JSON wrapping or other text.

Text to translate:
{text}
"""
        try:
            response = self.model.generate_content(
                prompt, 
                request_options={'timeout': 60}
            )
            return response.text.strip()
        except Exception as e:
            self.log(f"Text translation error: {e}")
            return f"Error: {e}"

    def _replace_text_in_excel(self, wb):
        count = 0
        for sheet in wb.worksheets:
            # Replace Sheet Title
            if sheet.title in self.translation_dict:
                sheet.title = self.translation_dict[sheet.title]
                count += 1

            for row in sheet.iter_rows():
                for cell in row:
                    # Replace Cell Value
                    if cell.value and isinstance(cell.value, str):
                        original_text = cell.value.strip()
                        if original_text in self.translation_dict:
                            translated_text = self.translation_dict[original_text]
                            if translated_text and translated_text != original_text:
                                cell.value = translated_text
                                count += 1
                    
                    # Replace Cell Comment (Memo)
                    if cell.comment and cell.comment.text:
                        original_comment = cell.comment.text.strip()
                        if original_comment in self.translation_dict:
                            cell.comment.text = self.translation_dict[original_comment]
                            count += 1
        self.log(f"Replaced {count} text instances in Excel (including sheet names and comments).")

    def _extract_unique_texts_text(self, content) -> list:
        unique_texts = set()
        lines = content.splitlines()
        for line in lines:
            text = line.strip()
            if text:
                unique_texts.add(text)
        
        self.sections = [{
            "name": "Text Content",
            "texts": list(unique_texts),
            "tone": "unknown"
        }]
        return list(unique_texts)

    def _replace_text_in_text(self, content) -> str:
        lines = content.splitlines(keepends=True)
        translated_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped in self.translation_dict:
                translated = self.translation_dict[stripped]
                # Try to preserve leading/trailing whitespace (roughly)
                leading = line[:line.find(stripped)]
                trailing = line[line.find(stripped) + len(stripped):]
                translated_lines.append(f"{leading}{translated}{trailing}")
            else:
                translated_lines.append(line)
        return "".join(translated_lines)

    def _extract_unique_texts_docx(self, doc) -> list:
        unique_texts = set()
        doc_texts = []
        
        # Paragraphs
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                unique_texts.add(text)
                doc_texts.append(text)
        
        # Tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        text = para.text.strip()
                        if text:
                            unique_texts.add(text)
                            doc_texts.append(text)
        
        self.sections = [{
            "name": "Word Document",
            "texts": doc_texts,
            "tone": "unknown"
        }]
        return list(unique_texts)

    def _apply_docx_paragraph_translation(self, para, translated: str):
        """Applies translated text to a docx paragraph while preserving run-level styling."""
        font_name = None
        font_size = None
        font_bold = None
        font_italic = None
        font_color_rgb = None

        target_run = None
        for r in para.runs:
            if r.text.strip():
                target_run = r
                break
        if not target_run and para.runs:
            target_run = para.runs[0]

        if target_run:
            font_name = target_run.font.name
            font_size = target_run.font.size
            font_bold = target_run.font.bold
            font_italic = target_run.font.italic
            try:
                if target_run.font.color and target_run.font.color.rgb:
                    font_color_rgb = target_run.font.color.rgb
            except Exception:
                pass

        para.text = ""

        # Handle tagged mixed-formatting spans
        if "<span" in translated:
            pattern = re.compile(r'<span\s+([^>]+)>(.*?)</span>', re.DOTALL)
            last_idx = 0
            from docx.shared import Pt, RGBColor

            for match in pattern.finditer(translated):
                start, end = match.span()
                if start > last_idx:
                    pre_text = translated[last_idx:start]
                    if pre_text:
                        r = para.add_run(pre_text)
                        if font_name: r.font.name = font_name
                        if font_size: r.font.size = font_size
                        if font_bold is not None: r.font.bold = font_bold
                        if font_italic is not None: r.font.italic = font_italic
                        if font_color_rgb: r.font.color.rgb = font_color_rgb

                attrs_str = match.group(1)
                inner_text = match.group(2)
                r = para.add_run(inner_text)
                if font_name: r.font.name = font_name
                if font_size: r.font.size = font_size
                if font_bold is not None: r.font.bold = font_bold
                if font_italic is not None: r.font.italic = font_italic
                if font_color_rgb: r.font.color.rgb = font_color_rgb

                cm = re.search(r'color=["\']#?([0-9a-fA-F]{6})["\']', attrs_str)
                if cm:
                    h = cm.group(1)
                    r.font.color.rgb = RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

                sm = re.search(r'size=["\']([0-9.]+)["\']', attrs_str)
                if sm:
                    try: r.font.size = Pt(float(sm.group(1)))
                    except: pass

                bm = re.search(r'bold=["\'](true|1)["\']', attrs_str, re.IGNORECASE)
                if bm:
                    r.font.bold = True
                elif re.search(r'bold=["\'](false|0)["\']', attrs_str, re.IGNORECASE):
                    r.font.bold = False

                last_idx = end

            if last_idx < len(translated):
                post_text = translated[last_idx:]
                if post_text:
                    r = para.add_run(post_text)
                    if font_name: r.font.name = font_name
                    if font_size: r.font.size = font_size
                    if font_bold is not None: r.font.bold = font_bold
                    if font_italic is not None: r.font.italic = font_italic
                    if font_color_rgb: r.font.color.rgb = font_color_rgb
            return

        new_run = para.add_run(translated)
        if font_name:
            new_run.font.name = font_name
        if font_size:
            new_run.font.size = font_size
        if font_bold is not None:
            new_run.font.bold = font_bold
        if font_italic is not None:
            new_run.font.italic = font_italic
        if font_color_rgb:
            try:
                new_run.font.color.rgb = font_color_rgb
            except Exception:
                pass

    def _replace_text_in_docx(self, doc):
        count = 0
        # Paragraphs
        for para in doc.paragraphs:
            original = para.text.strip()
            if original in self.translation_dict:
                translated = self.translation_dict[original]
                if translated and translated != original:
                    self._apply_docx_paragraph_translation(para, translated)
                    count += 1

        # Tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        original = para.text.strip()
                        if original in self.translation_dict:
                            translated = self.translation_dict[original]
                            if translated and translated != original:
                                self._apply_docx_paragraph_translation(para, translated)
                                count += 1
        self.log(f"Replaced {count} text instances in Word document.")

    def process_markdown(self, input_file) -> io.BytesIO:
        """
        Processes a Markdown file (file-like object) and returns the translated
        Markdown as a BytesIO object, preserving all syntax (headers, lists,
        code blocks, links, images, etc.).
        """
        self.check_cancelled()
        self.log("Reading Markdown file...")
        content = input_file.read().decode('utf-8', errors='ignore')

        self.check_cancelled()
        self.log("Extracting translatable text from Markdown...")
        unique_texts = self._extract_unique_texts_markdown(content)
        self.log(f"Found {len(unique_texts)} unique text chunks.")

        self.check_cancelled()
        self.log("Analyzing tone...")
        self._analyze_tones()

        self.check_cancelled()
        if unique_texts:
            self.log("Starting translation...")
            self.translation_dict = self._translate_texts(unique_texts)
            self.log("Translation complete.")
        else:
            self.log("No text found to translate.")

        self.check_cancelled()
        self.log("Applying translations to Markdown...")
        translated_content = self._replace_text_in_markdown(content)

        output = io.BytesIO()
        output.write(translated_content.encode('utf-8'))
        output.seek(0)
        self.log("Processing finished.")
        return output

    def _extract_unique_texts_markdown(self, content: str) -> list:
        """
        Extracts translatable text from Markdown, intelligently skipping:
        - Fenced code blocks (```...```)
        - Inline code (`...`)
        - Image/link URLs
        - Raw HTML tags
        - Blank lines
        For headers (# Text), it extracts only the text portion.
        For other lines, it strips leading Markdown punctuation (*, -, >, etc.).
        """
        unique_texts = set()
        doc_texts = []
        in_code_block = False

        lines = content.splitlines()
        for line in lines:
            stripped = line.strip()

            # Toggle fenced code block
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_code_block = not in_code_block
                continue

            if in_code_block:
                continue

            if not stripped:
                continue

            # Strip leading Markdown syntax to get the raw text
            # Headings: # / ## / etc.
            heading_match = re.match(r'^#{1,6}\s+(.*)', stripped)
            if heading_match:
                text = heading_match.group(1).strip()
            else:
                # List items: *, -, +, or numbered 1.
                list_match = re.match(r'^(?:[*\-+]|\d+\.)\s+(.*)', stripped)
                if list_match:
                    text = list_match.group(1).strip()
                else:
                    # Blockquotes: >
                    bq_match = re.match(r'^>+\s*(.*)', stripped)
                    if bq_match:
                        text = bq_match.group(1).strip()
                    else:
                        text = stripped

            # Skip lines that are purely Markdown syntax or HTML
            if not text or re.match(r'^[\-=_*]{3,}$', text):  # Horizontal rules
                continue
            if re.match(r'^<.*>$', text):  # Pure HTML tags
                continue

            # Remove inline code before sending to translation
            text_no_code = re.sub(r'`[^`]+`', '', text).strip()
            if not text_no_code:
                continue

            if text_no_code not in unique_texts:
                unique_texts.add(text_no_code)
                doc_texts.append(text_no_code)

        self.sections = [{
            "name": "Markdown Document",
            "texts": doc_texts,
            "tone": "unknown"
        }]
        return list(unique_texts)

    def _replace_text_in_markdown(self, content: str) -> str:
        """
        Replaces extracted text segments in the Markdown content with their
        translations, preserving all structural syntax.
        """
        in_code_block = False
        result_lines = []

        lines = content.splitlines(keepends=True)
        for line in lines:
            stripped = line.strip()

            # Toggle fenced code block
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_code_block = not in_code_block
                result_lines.append(line)
                continue

            if in_code_block or not stripped:
                result_lines.append(line)
                continue

            # Determine leading syntax prefix and extract text
            prefix = ''
            heading_match = re.match(r'^(#{1,6}\s+)(.*)', stripped)
            if heading_match:
                prefix = heading_match.group(1)
                text = heading_match.group(2).strip()
            else:
                list_match = re.match(r'^([*\-+]|\d+\.)\s+(.*)', stripped)
                if list_match:
                    prefix = list_match.group(1) + ' '
                    text = list_match.group(2).strip()
                else:
                    bq_match = re.match(r'^(>+\s*)(.*)', stripped)
                    if bq_match:
                        prefix = bq_match.group(1)
                        text = bq_match.group(2).strip()
                    else:
                        prefix = ''
                        text = stripped

            # Strip inline code from key lookup
            text_no_code = re.sub(r'`[^`]+`', '', text).strip()

            if text_no_code and text_no_code in self.translation_dict:
                translated = self.translation_dict[text_no_code]
                # Preserve original leading whitespace from the line
                leading_ws = line[:len(line) - len(line.lstrip())]
                trailing_nl = '\n' if line.endswith('\n') else ''
                result_lines.append(f"{leading_ws}{prefix}{translated}{trailing_nl}")
            else:
                result_lines.append(line)

        return ''.join(result_lines)

    def process_csv(self, input_file) -> io.BytesIO:
        """
        Processes a CSV file (file-like object) and returns the translated CSV
        as a BytesIO object, perfectly preserving row/column structure and
        any non-string (numeric) cells.
        """
        self.check_cancelled()
        self.log("Reading CSV file...")
        content = input_file.read().decode('utf-8-sig', errors='ignore')  # Handle BOM
        reader = csv.reader(content.splitlines())
        rows = list(reader)

        self.check_cancelled()
        self.log("Extracting translatable text from CSV...")
        unique_texts = self._extract_unique_texts_csv(rows)
        self.log(f"Found {len(unique_texts)} unique text chunks.")

        self.check_cancelled()
        self.log("Analyzing tone...")
        self._analyze_tones()

        self.check_cancelled()
        if unique_texts:
            self.log("Starting translation...")
            self.translation_dict = self._translate_texts(unique_texts)
            self.log("Translation complete.")
        else:
            self.log("No text found to translate.")

        self.check_cancelled()
        self.log("Applying translations to CSV...")
        translated_rows = self._replace_text_in_csv(rows)

        output = io.BytesIO()
        # Write using a string buffer, then encode
        import io as _io
        str_buffer = _io.StringIO()
        writer = csv.writer(str_buffer)
        writer.writerows(translated_rows)
        output.write(str_buffer.getvalue().encode('utf-8'))
        output.seek(0)
        self.log("Processing finished.")
        return output

    def _extract_unique_texts_csv(self, rows: list) -> list:
        """Extracts all non-empty string cells from a list of CSV rows."""
        unique_texts = set()
        all_texts = []
        for row in rows:
            for cell in row:
                text = cell.strip()
                # Only translate non-empty strings that aren't purely numeric
                if text and not self._is_numeric(text) and text not in unique_texts:
                    unique_texts.add(text)
                    all_texts.append(text)
        self.sections = [{
            "name": "CSV Document",
            "texts": all_texts,
            "tone": "unknown"
        }]
        return list(unique_texts)

    def _replace_text_in_csv(self, rows: list) -> list:
        """Replaces text cells in CSV rows with their translations."""
        count = 0
        translated_rows = []
        for row in rows:
            new_row = []
            for cell in row:
                text = cell.strip()
                if text and not self._is_numeric(text) and text in self.translation_dict:
                    new_row.append(self.translation_dict[text])
                    count += 1
                else:
                    new_row.append(cell)
            translated_rows.append(new_row)
        self.log(f"Replaced {count} text instances in CSV.")
        return translated_rows

    @staticmethod
    def _is_numeric(text: str) -> bool:
        """Returns True if the string represents a pure number (int or float)."""
        try:
            float(text.replace(',', ''))
            return True
        except ValueError:
            return False

    def process_json(self, input_file) -> io.BytesIO:
        """
        Processes a JSON file, translating string values while preserving keys
        and structure.
        """
        self.check_cancelled()
        self.log("Reading JSON file...")
        content = input_file.read().decode('utf-8', errors='ignore')
        try:
            data = json.loads(content)
        except Exception as e:
            self.log(f"JSON Parse Error: {e}")
            raise e

        self.check_cancelled()
        self.log("Extracting translatable strings from JSON...")
        unique_texts = set()
        doc_texts = []
        
        def _extract(obj):
            if isinstance(obj, str):
                text = obj.strip()
                if text and not self._is_numeric(text):
                    if text not in unique_texts:
                        unique_texts.add(text)
                        doc_texts.append(text)
            elif isinstance(obj, dict):
                for v in obj.values():
                    _extract(v)
            elif isinstance(obj, list):
                for item in obj:
                    _extract(item)
        
        _extract(data)
        self.log(f"Found {len(unique_texts)} unique text strings.")

        self.check_cancelled()
        self.log("Analyzing tone...")
        self.sections = [{"name": "JSON Document", "texts": doc_texts, "tone": "unknown"}]
        self._analyze_tones()

        self.check_cancelled()
        if unique_texts:
            self.log("Starting translation...")
            self.translation_dict = self._translate_texts(list(unique_texts))
            self.log("Translation complete.")
        else:
            self.log("No text found to translate.")

        self.check_cancelled()
        self.log("Applying translations to JSON...")
        
        def _replace(obj):
            if isinstance(obj, str):
                text = obj.strip()
                if text in self.translation_dict:
                    return self.translation_dict[text]
                return obj
            elif isinstance(obj, dict):
                return {k: _replace(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_replace(item) for item in obj]
            return obj

        translated_data = _replace(data)
        
        output = io.BytesIO()
        output.write(json.dumps(translated_data, ensure_ascii=False, indent=2).encode('utf-8'))
        output.seek(0)
        self.log("Processing finished.")
        return output

    def process_html(self, input_file) -> io.BytesIO:
        """
        Processes an HTML file, translating text nodes while preserving all
        tags, attributes, scripts, and styles.
        """
        self.check_cancelled()
        self.log("Reading HTML file...")
        content = input_file.read().decode('utf-8', errors='ignore')

        self.check_cancelled()
        self.log("Extracting text from HTML...")
        
        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.texts = []
                self.skip_tags = {'script', 'style', 'code', 'pre'}
                self.current_tag = None

            def handle_starttag(self, tag, attrs):
                self.current_tag = tag

            def handle_data(self, data):
                if self.current_tag not in self.skip_tags:
                    text = data.strip()
                    if text and not any(c in text for c in '{}'): # Filter out JS code/CSS braces
                        self.texts.append(text)
            
            def handle_endtag(self, tag):
                self.current_tag = None

        extractor = TextExtractor()
        extractor.feed(content)
        unique_texts = list(set(extractor.texts))
        self.log(f"Found {len(unique_texts)} unique text nodes.")

        self.check_cancelled()
        self.log("Analyzing tone...")
        self.sections = [{"name": "HTML Document", "texts": extractor.texts, "tone": "unknown"}]
        self._analyze_tones()

        self.check_cancelled()
        if unique_texts:
            self.log("Starting translation...")
            self.translation_dict = self._translate_texts(unique_texts)
            self.log("Translation complete.")
        else:
            self.log("No text found to translate.")

        self.check_cancelled()
        self.log("Applying translations to HTML...")
        
        # We replace text nodes carefully. To avoid replacing things inside tags, 
        # we can't just do a global replace. 
        # A safer way is to use a parser to identify the points of replacement.
        # But for "Reliable Reconstruction", we want to change as little of the raw string as possible.
        
        # Let's use a simple approach: find segments of data that match our unique texts
        # and replace them ONLY if they are not inside <...>.
        
        translated_content = content
        
        # To avoid nested replacement issues (replacing "A" and then "AB"), 
        # we sort unique texts by length descending.
        sorted_texts = sorted(unique_texts, key=len, reverse=True)
        
        for original in sorted_texts:
            if original in self.translation_dict:
                translated = self.translation_dict[original]
                if translated and translated != original:
                    # Escape for regex
                    escaped = re.escape(original)
                    # Look for text NOT preceded by < and NOT followed by > (naive but often works)
                    # A better way is to split the content by tags and only replace in text parts.
                    parts = re.split(r'(<[^>]+>)', translated_content)
                    for i in range(len(parts)):
                        if not parts[i].startswith('<'):
                            # Replace occurrences of 'original' in this text segment
                            # We use escaped regex to match exactly
                            parts[i] = parts[i].replace(original, translated)
                    translated_content = "".join(parts)

        output = io.BytesIO()
        output.write(translated_content.encode('utf-8'))
        output.seek(0)
        self.log("Processing finished.")
        return output


    def process_pdf(self, input_file) -> io.BytesIO:
        """
        Processes a PDF document (file-like object or bytes) and returns the translated PDF as a BytesIO object.
        Delegates to DigitalPdfHandler, which automatically switches to ScannedPdfHandler if no digital text is found.
        """
        from backend.handlers.pdf_digital import DigitalPdfHandler
        return DigitalPdfHandler(self).process(input_file)

    def process_scanned_pdf(self, doc) -> io.BytesIO:
        """
        Base implementation for scanned PDF translation.
        """
        from backend.handlers.pdf_scanned import ScannedPdfHandler
        return ScannedPdfHandler(self).process_doc(doc)

    def process_image(self, input_file, ext: str) -> io.BytesIO:
        """
        Base implementation for image translation.
        """
        from backend.handlers.image_handler import ImageDocumentHandler
        return ImageDocumentHandler(self).process(input_file, ext=ext)

    @staticmethod
    def _fix_ordered_lists_for_fitz(html_text: str) -> str:
        """
        PyMuPDF's insert_htmlbox ignores <ol start="N"> and always numbers ordered lists starting from 1.
        This helper transforms <ol> lists into explicitly numbered blocks with hanging indents,
        preserving the exact starting numbers (e.g., 30., 31., 32.) and nested hierarchy.
        """
        def replace_ol(match):
            start_attr = match.group(1)
            content = match.group(2)
            start_num = int(start_attr) if start_attr else 1
            items = re.findall(r'<li(?:[^>]*)>(.*?)</li>', content, re.DOTALL)
            res = []
            for idx, item in enumerate(items):
                clean_item = item.strip()
                res.append(
                    f'<p style="margin: 2.5pt 0 2.5pt 16pt; text-indent: -16pt; line-height: 1.4;">'
                    f'<strong>{start_num + idx}.</strong> {clean_item}</p>'
                )
            return '\n'.join(res)

        pattern = re.compile(r'<ol(?:\s+start=[\"\'](\d+)[\"\'])?[^>]*>(.*?)</ol>', re.DOTALL)
        prev = ""
        curr = html_text
        while prev != curr:
            prev = curr
            curr = pattern.sub(replace_ol, curr)
        return curr

    def _review_document_pages(self, translated_pages: dict, max_review_loops: int = 2) -> dict:
        """
        Base stub for post-translation review loop. Subclasses override this.
        """
        return translated_pages

    @staticmethod
    def list_available_models(api_key: Optional[str] = None):
        """
        Fetches available Gemini models that support multimodal content generation.
        Filters specifically for modern multimodal models (Gemini 1.5, 2.0, 2.5, 3.0+)
        and excludes non-multimodal, deprecated, internal, or dated snapshot duplicates.
        Returns a list of dicts with 'id' and 'name'.
        """
        if not api_key:
            try:
                from backend.core.cloud_secrets import get_gemini_api_key
                api_key = get_gemini_api_key()
            except Exception:
                pass
        if not api_key:
            raise ValueError("API Key is required to query available Gemini models.")
        try:
            client = _genai.Client(
                api_key=api_key,
                http_options={"api_version": "v1beta"},
            )
            models = []
            for m in client.models.list():
                # New SDK: check supported_actions (list of str) not supported_generation_methods
                supported_actions = getattr(m, 'supported_actions', None) or []
                if supported_actions and 'generateContent' not in supported_actions:
                    continue

                name = m.name.replace('models/', '')
                name_lower = name.lower()
                desc = getattr(m, 'description', '') or ''

                # Must be a Gemini model
                if not name_lower.startswith('gemini-'):
                    continue

                # Exclude non-multimodal, embedding, audio-only, nano/banana, experimental, or specialized models
                excluded_keywords = [
                    'nano', 'banana', '8b', 'exp', 'experimental', 'thinking', 'learnlm', 'gemma',
                    'embedding', 'aqa', 'retrieval', 'imagen', 'tts', 'audio',
                    'robotics', 'computer-use', 'custom', 'tuning', 'tunedmodels'
                ]
                display_name_raw = getattr(m, 'display_name', '') or ''
                if any(x in name_lower or x in desc.lower() or x in display_name_raw.lower() for x in excluded_keywords):
                    continue

                # Exclude deprecated legacy 1.0 series (gemini-1.0-pro, gemini-pro-vision, etc.)
                if '1.0' in name_lower or name_lower in ['gemini-pro', 'gemini-pro-vision']:
                    continue

                # Exclude dated pinned snapshots (e.g., gemini-1.5-flash-001, gemini-1.5-pro-002, etc.)
                if re.search(r'-\d{3,8}$', name_lower):
                    continue

                # Must be a production Pro or Flash tier model for document/image translation
                if not ('pro' in name_lower or 'flash' in name_lower):
                    continue

                # Must be modern multimodal series (1.5, 2.x, 2.5, 3.x, etc.) or explicitly multimodal in description
                has_modern_version = any(ver in name_lower for ver in ['1.5', '2.', '3.', '3-', '4.', '5.'])
                is_multimodal = has_modern_version or 'multimodal' in desc.lower() or 'image' in desc.lower()

                if is_multimodal:
                    display_name = getattr(m, 'display_name', None)
                    if not display_name or str(display_name).lower().startswith('models/'):
                        display_name = name.replace('-', ' ').title()
                    models.append({
                        "id": name,
                        "name": display_name
                    })

            def sort_key(item):
                name = item["id"].lower()
                version_match = re.search(r'gemini-(\d+(?:\.\d+)?)', name)
                version_val = float(version_match.group(1)) if version_match else 0.0
                score = version_val * 100
                if "pro" in name:
                    score += 20
                elif "flash" in name:
                    score += 10
                return -score

            models.sort(key=sort_key)
            return models
        except Exception as e:
            print(f"Error listing models: {e}")
            raise e

class GeminiTranslator(BaseTranslator):
    @staticmethod
    def clean_model_id(val: str) -> str:
        """
        Converts any model name, display name, or model URI into a canonical
        Google Generative AI model identifier (e.g. 'gemini-3.8-pro', 'gemini-3.8-flash').
        Dynamically handles any current or future model without hardcoded lists.
        """
        if not val:
            return "gemini-3.8-flash"

        s = str(val).strip()
        # Strip models/ prefix if present
        if s.lower().startswith("models/"):
            s = s[7:]

        # If already in valid canonical kebab-case format (e.g. gemini-3.8-pro)
        if re.match(r'^gemini-[a-z0-9.-]+$', s):
            return s

        # Normalize display name: lowercase, convert spaces to hyphens
        s = s.lower()
        s = re.sub(r'\s+', '-', s)
        s = re.sub(r'[^a-z0-9.-]', '', s)

        # Prepend gemini- if not already present
        if not s.startswith("gemini-"):
            s = f"gemini-{s}"

        return s

    def __init__(self, api_key: Optional[str] = None, target_lang: str = 'Japanese', model_name: str = 'gemini-3.8-flash', log_callback=None, stop_event=None):
        super().__init__(target_lang, log_callback, stop_event)
        if not api_key:
            try:
                from backend.core.cloud_secrets import get_gemini_api_key
                api_key = get_gemini_api_key()
            except Exception:
                pass
        self.api_key = api_key or ""
        self.model_name = self.clean_model_id(model_name)
        from backend.core.model_client import create_model
        self.model = create_model(self.model_name, self.api_key)
        reviewer_name = os.getenv("TRANSLATOR_REVIEW_MODEL", self.model_name)
        self.review_model_name = reviewer_name
        self.review_model = create_model(reviewer_name, self.api_key)

    def _analyze_tones(self):
        """
        Uses Gemini to determine the overall tone and tone of each section.
        """
        # 1. Overall Document Tone
        all_texts = []
        for section in self.sections:
            all_texts.extend(section["texts"])
        
        # Sample to avoid huge tokens, but enough for context
        sample_text = "\n".join(all_texts[:50]) 
        
        prompt_overall = f"""
        Analyze the overall tone and identify the source language of the following document content. 
        Provide the result as a JSON object with two fields: "tone" and "language".
        - "tone": A very brief description (3-5 words) of the tone (e.g., "Professional and formal").
        - "language": The name of the source language (e.g., "Korean", "English").
        
        Content:
        {sample_text}
        
        JSON Result:
        """
        try:
            response = self.model.generate_content(
                prompt_overall, 
                generation_config={"response_mime_type": "application/json"},
                request_options={'timeout': 20}
            )
            analysis = json.loads(response.text.strip())
            self.overall_tone = analysis.get("tone", "business professional")
            self.source_lang = analysis.get("language", "Auto-detect")
            self.log(f"Detected Source Language: {self.source_lang}")
            self.log(f"Detected Overall Tone: {self.overall_tone}")
        except Exception as e:
            self.log(f"Failed to detect tone/language: {e}")

        # 2. Section Tones
        # Concurrently analyze section tones using ThreadPoolExecutor
        active_sections = [s for s in self.sections if s.get("texts")]
        if active_sections:
            def _analyze_single_section(sec: dict) -> tuple[dict, str]:
                self.check_cancelled()
                sec_sample = "\n".join(sec["texts"][:10])
                prompt_sec = f"Describe the specific tone of this section in 3 words: \n\n{sec_sample}"
                try:
                    res = self.model.generate_content(prompt_sec, request_options={'timeout': 15})
                    tone_text = res.text.strip() if res and res.text else self.overall_tone
                    return sec, tone_text
                except Exception:
                    return sec, self.overall_tone

            workers = min(4, len(active_sections))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(_analyze_single_section, s) for s in active_sections]
                for fut in futures:
                    self.check_cancelled()
                    sec, tone = fut.result()
                    sec["tone"] = tone

    def _translate_texts(self, texts: list) -> dict:
        """
        Translates a list of texts using Gemini concurrently via ThreadPoolExecutor,
        with logs preserved in strict logical sequence via a Sequenced Release Buffer.
        """
        if not texts:
            return {}

        translation_map = {}
        BATCH_SIZE = 10
        total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

        # Prepare batches
        batches = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch_slice = texts[i:i + BATCH_SIZE]
            b_idx = i // BATCH_SIZE
            batch_context = []
            for text in batch_slice:
                rel_sections = [s["name"] for s in self.sections if text in s.get("texts", [])]
                rel_tones = [s["tone"] for s in self.sections if text in s.get("texts", [])]
                batch_context.append({
                    "text": text,
                    "sections": rel_sections,
                    "tones": rel_tones,
                })
            batches.append((b_idx, batch_slice, batch_context))

        rules = get_rules(self.source_lang, self.target_lang)

        def translate_single_batch(
            b_idx: int,
            batch_slice: list[str],
            batch_ctx: list[dict],
        ) -> tuple[int, dict[str, str], list[str]]:
            local_logs: list[str] = []
            local_map: dict[str, str] = {}
            current_batch = b_idx + 1

            local_logs.append(
                f"Translating batch {current_batch}/{total_batches} "
                f"(items {b_idx * BATCH_SIZE + 1} to {min((b_idx + 1) * BATCH_SIZE, len(texts))}) with {self.model_name}..."
            )

            prompt = f"""You have three tasks to complete in sequence for each item in the provided list. 
You only need to output the final result, which is the naturalized translation from {self.source_lang} to {self.target_lang}.

**Overall Document Context:**
- Source Language: {self.source_lang}
- Target Language: {self.target_lang}
- Overall Tone: {self.overall_tone}

--------------------------------------------------------------------------------------------------------------------

1. First task (Rule Application)
Apply the following specialized translation rules for {self.source_lang} to {self.target_lang} translation:

**
{rules}
**

--------------------------------------------------------------------------------------------------------------------

2. Second task (Translation)
Translate each text provided in the list from {self.source_lang} to {self.target_lang}, using the rules from the first task and the item-specific context (section and tone).

--------------------------------------------------------------------------------------------------------------------

3. Third task (Naturalization)
Make sure the translated texts sound natural as if they were originally written in {self.target_lang}. 
Return the final result as a JSON object where keys are the original texts and values are the final naturalized translations.

**Texts to translate with context:**
{json.dumps(batch_ctx, ensure_ascii=False)}

JSON Result:
"""
            try:
                self.check_cancelled()
                response = self.model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"},
                    request_options={'timeout': 600},
                )
                self.check_cancelled()

                content = response.text.strip() if (response and response.text) else ""
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]

                try:
                    batch_translations_raw = json.loads(content)
                    if isinstance(batch_translations_raw, dict):
                        for orig, trans in batch_translations_raw.items():
                            local_map[orig.strip()] = trans
                    elif isinstance(batch_translations_raw, list):
                        for item in batch_translations_raw:
                            if isinstance(item, dict):
                                orig = item.get("text") or item.get("original")
                                trans = item.get("translation") or item.get("translated") or item.get("value")
                                if orig and trans:
                                    local_map[orig.strip()] = trans
                                elif len(item) == 1:
                                    for k, v in item.items():
                                        local_map[k.strip()] = v
                    local_logs.append(f"Batch {current_batch}/{total_batches}: Mapped {len(local_map)} translations.")
                except Exception as parse_e:
                    local_logs.append(f"Batch {current_batch}: JSON parse warning ({parse_e}). Falling back to individual retry.")
            except Exception as batch_e:
                if "404" in str(batch_e):
                    local_logs.append(f"CRITICAL ERROR: Model {self.model_name} not found or not supported.")
                    raise batch_e
                local_logs.append(f"Batch {current_batch} failed ({batch_e}). Retrying individually...")

            # Fallback for any items in this batch that remain unmapped
            missing_items = [t for t in batch_slice if t.strip() not in local_map and t not in local_map]
            if missing_items:
                for text_item in missing_items:
                    self.check_cancelled()
                    try:
                        ind_prompt = f"Translate the following text into {self.target_lang}. Return ONLY the translated text.\n\nText: {text_item}"
                        ind_response = self.model.generate_content(ind_prompt, request_options={'timeout': 15})
                        translated_text = ind_response.text.strip() if ind_response and ind_response.text else text_item
                        local_map[text_item] = translated_text
                    except Exception as ind_err:
                        local_logs.append(f"Failed to translate item '{text_item[:40]}...': {ind_err}")
                        local_map[text_item] = text_item

            return b_idx, local_map, local_logs

        # Execute batches concurrently with ThreadPoolExecutor and Sequenced Release Buffer
        workers = min(4, total_batches)
        completed_buffer: dict[int, tuple[dict[str, str], list[str]]] = {}
        next_expected_batch = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {}
            for b_idx, b_slice, b_ctx in batches:
                self.check_cancelled()
                fut = executor.submit(translate_single_batch, b_idx, b_slice, b_ctx)
                future_to_idx[fut] = b_idx
                time.sleep(0.15)  # Gentle submission pacing to avoid burst RPM spikes

            for fut in as_completed(future_to_idx):
                self.check_cancelled()
                b_idx, b_map, b_logs = fut.result()
                completed_buffer[b_idx] = (b_map, b_logs)

                # Sequenced release: flush in strict monotonic order (0, 1, 2...)
                while next_expected_batch in completed_buffer:
                    sub_map, sub_logs = completed_buffer.pop(next_expected_batch)
                    for msg in sub_logs:
                        self.log(msg)
                    translation_map.update(sub_map)
                    next_expected_batch += 1

        return translation_map

    def process_image(self, input_file, ext: str) -> io.BytesIO:
        """
        Translates text in an image (PNG, JPG, WEBP) using Gemini Vision with universal layout rules.
        """
        from backend.handlers.image_handler import ImageDocumentHandler
        return ImageDocumentHandler(self).process(input_file, ext=ext)

    def process_scanned_pdf(self, doc) -> io.BytesIO:
        """
        Translates a scanned PDF (image-based pages with no digital text layer)
        using Gemini Vision with universal layout preservation rules and PyMuPDF HTML typesetting.
        """
        from backend.handlers.pdf_scanned import ScannedPdfHandler
        return ScannedPdfHandler(self).process_doc(doc)

    def _review_document_pages(self, translated_pages: dict, max_review_loops: int = 2) -> dict:
        """
        Audits the multi-page translated Markdown content using DocumentReviewEngine.
        """
        try:
            from backend.engines.review_engine import DocumentReviewEngine
        except ImportError:
            from backend.review_engine import DocumentReviewEngine
        engine = DocumentReviewEngine(
            model=self.model,
            target_lang=self.target_lang,
            log_callback=self.log,
            check_cancelled=self.check_cancelled
        )
        return engine.review_pages(translated_pages, max_review_loops=max_review_loops)




_LANG_CODE_MAP = {
    "japanese": "ja",
    "korean": "ko",
    "english": "en",
    "chinese (simplified)": "zh-CN",
    "chinese (traditional)": "zh-TW",
    "simplified chinese": "zh-CN",
    "traditional chinese": "zh-TW",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "vietnamese": "vi",
    "thai": "th",
    "indonesian": "id",
    "arabic": "ar",
    "hindi": "hi",
}


def _free_google_translate(text: str, target_lang: str) -> str:
    """
    Direct HTTPS query to Google Translate public endpoint.
    Zero external dependencies, highly resilient.
    """
    if not text.strip():
        return ""
    code = _LANG_CODE_MAP.get(target_lang.strip().lower(), target_lang.strip())
    url = (
        "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl="
        + urllib.parse.quote(code)
        + "&dt=t&q="
        + urllib.parse.quote(text)
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return "".join(chunk[0] for chunk in data[0] if chunk[0])


class GoogleTransTranslator(BaseTranslator):
    def __init__(self, target_lang: str = 'Japanese', log_callback=None, stop_event=None):
        super().__init__(target_lang, log_callback, stop_event)
        self.dest_code = _LANG_CODE_MAP.get(target_lang.strip().lower(), target_lang.strip())

    def _translate_single(self, text: str) -> str:
        try:
            return _free_google_translate(text, self.dest_code)
        except Exception as e:
            self.log(f"Google Translate error on chunk: {e}")
            return text

    def _translate_texts(self, texts: list) -> dict:
        translation_map = {}
        if not texts:
            return translation_map

        self.log(f"Translating {len(texts)} items with Google Translate to '{self.dest_code}'...")

        # Concurrently translate with ThreadPoolExecutor
        max_workers = min(8, len(texts))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_text = {executor.submit(self._translate_single, t): t for t in texts}
            completed = 0
            for future in as_completed(future_to_text):
                self.check_cancelled()
                orig = future_to_text[future]
                try:
                    res = future.result()
                    translation_map[orig] = res
                except Exception as exc:
                    self.log(f"Translation failed for '{orig[:20]}...': {exc}")
                    translation_map[orig] = orig
                completed += 1
                if completed % 10 == 0 or completed == len(texts):
                    self.log(f"Translated {completed}/{len(texts)} chunks...")

        self.log("Translation complete.")
        return translation_map

    def translate_text(self, text: str) -> str:
        """
        Translates a single block of text using Google Translate.
        """
        if not text.strip():
            return ""
        self.check_cancelled()
        try:
            return _free_google_translate(text, self.dest_code)
        except Exception as e:
            self.log(f"Google Translate error: {e}")
            return f"Error: {e}"

    def process_image(self, input_file, ext: str) -> io.BytesIO:
        raise ValueError("Image translation requires a vision AI model. Please choose a Gemini model.")

    def process_scanned_pdf(self, doc) -> io.BytesIO:
        raise ValueError(
            "This document is a scanned PDF (image-only with no digital text layer). "
            "Scanned document translation requires a multimodal AI vision model. "
            "Please select a Gemini model (e.g. Gemini 3.1 Pro or Gemini 2.5 Flash) and provide your API key."
        )

