"""Fail-closed PDF typesetting and deterministic rendered-content checks."""
from __future__ import annotations

import fitz
import markdown
import html
import re
import unicodedata
from collections import Counter

from backend.quality.models import Finding


def checked_text_box(text: str, width: float, height: float, size: float, color: int, bold=False):
    """Validate extracted glyph coverage before committing text over source art.

    Older MuPDF versions can report successful HTML insertion while clipping an
    unbreakable word horizontally. Rendering to an isolated page catches that
    case without leaving failed attempts in the real document.
    """
    def characters(value):
        return Counter(re.sub(r'[\s\u00ad\u200b]', '', unicodedata.normalize('NFKC', value)))
    expected = characters(text)
    for scale in (1, .8, .64, .512, .4096, .32768, .262144):
        document = fitz.open()
        page = document.new_page(width=width, height=height)
        css = (f'body {{margin:0;padding:0;font-family:sans-serif;font-size:{size * scale}pt;'
               f'line-height:1.05;color:#{color:06x};font-weight:{"bold" if bold else "normal"};}}')
        spare, _ = page.insert_htmlbox(page.rect, html.escape(text).replace('\n','<br>'), css=css, scale_low=1)
        if spare >= 0 and characters(page.get_text()) == expected:
            result = document.tobytes(garbage=4, deflate=True)
            document.close()
            return result, scale
        document.close()
    raise ValueError('Translated text cannot fit with complete glyph coverage.')


def page_is_blank(page) -> bool:
    """Inspect pixels as well as text so scanned pages and vector art count."""
    if page.get_text().strip():
        return False
    pixels = page.get_pixmap(matrix=fitz.Matrix(.25, .25), colorspace=fitz.csGRAY, alpha=False)
    return not any(value < 245 for value in pixels.samples)


def checked_markdown_page(content: str, width: float, height: float, target_lang: str):
    """Try normal then compact layout on fresh pages; never accept failed insertion."""
    from backend.engines.layout_engine import render_markdown_to_html
    if not content.strip():
        raise ValueError('Cannot typeset an empty translated page.')
    from bs4 import BeautifulSoup
    content_without_page_markers = re.sub(r'\[Page:\s*\d+\]', '', content, flags=re.I)
    plain = BeautifulSoup(markdown.markdown(content_without_page_markers, extensions=['tables']), 'html.parser').get_text()
    def letters(value):
        return Counter(re.sub(r'[\W_]', '', unicodedata.normalize('NFKC', value).casefold()))
    expected = letters(plain)
    normal = render_markdown_to_html(content, target_lang=target_lang)
    # Keep the same structural renderer in the fallback: plain Markdown rendering
    # collapses non-Markdown numbered lists and exposes internal page markers.
    compact_css = ('body {font-size:10pt;margin:0;} '
                   '.doc-paragraph,.doc-item,.doc-clause,.doc-subitem {margin:3pt 0;} '
                   'table {border-collapse:collapse;width:100%;font-size:8pt;} '
                   'td,th {padding:2pt;} img {max-width:100%;}')
    compact = render_markdown_to_html(content, target_lang=target_lang).replace('</style>', compact_css + '</style>')
    margin = min(24, width * .04, height * .04)
    for index, html in enumerate((normal, compact)):
        document = fitz.open()
        page = document.new_page(width=width, height=height)
        spare, scale = page.insert_htmlbox(fitz.Rect(margin, margin, width-margin, height-margin), html,
                                           scale_low=.45 if index == 0 else .2)
        extracted = page.get_text()
        if spare >= 0 and extracted.strip() and not (expected - letters(extracted)) and not page_is_blank(page):
            findings = []
            if index:
                findings.append(Finding('compact_layout', 'Used a compact layout after the standard page did not fit.'))
            if scale < .45:
                findings.append(Finding('small_text', f'Page content required scaling to {scale:.2f}; inspect readability.'))
            data = document.tobytes(garbage=4, deflate=True)
            document.close()
            return data, findings
        document.close()
    raise ValueError('Translated page cannot be rendered without blank or overflowing output.')
