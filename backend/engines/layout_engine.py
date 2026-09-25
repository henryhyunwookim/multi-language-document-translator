"""
Universal Document Layout & Typesetting Engine.
Provides language-independent and document-agnostic HTML/CSS generation,
markdown normalization, line break preservation, list cleanup, stamp rendering,
hierarchical Table of Contents formatting, hanging indents for legal clauses,
and typography management for PDF and HTML output.
"""

import re
from typing import Optional, Tuple, List
import markdown
from bs4 import BeautifulSoup


def build_document_css(target_lang: str = "English", is_cover: bool = False) -> str:
    """
    Builds a professional typography stylesheet for document reconstruction.
    Adapts font stacks according to the target language (CJK vs Western).
    """
    target_lower = target_lang.lower()
    if any(cjk in target_lower for cjk in ["japan", "chin", "korea", "thai"]):
        font_stack = "'Malgun Gothic', 'Noto Sans CJK KR', 'Noto Sans CJK JP', 'Hiragino Sans', 'Yu Gothic', 'Microsoft YaHei', sans-serif"
    else:
        font_stack = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

    if is_cover:
        return f"""
        body {{
            font-family: {font_stack};
            font-size: 10pt;
            line-height: 1.5;
            color: #0f172a;
            margin: 0;
            padding: 0;
            text-align: center;
        }}
        .cover-title {{
            font-size: 24pt;
            font-weight: 700;
            color: #0f172a;
            margin-top: 180pt;
            margin-bottom: 200pt;
            letter-spacing: 1.5pt;
            text-align: center;
        }}
        .cover-date {{
            font-size: 11pt;
            color: #334155;
            margin-bottom: 24pt;
            text-align: center;
        }}
        .cover-stamp-container {{
            margin-top: 20pt;
            text-align: right;
            padding-right: 20pt;
        }}
        .stamp-table {{
            margin-left: auto;
            margin-right: 20pt;
            border: 1.5pt solid #dc2626;
            border-radius: 4pt;
            color: #dc2626;
            font-size: 8.5pt;
            font-weight: bold;
            text-align: center;
            width: auto;
        }}
        .stamp-table td {{
            padding: 6pt 12pt;
            border: none;
            line-height: 1.4;
        }}
        """

    return f"""
    body {{
        font-family: {font_stack};
        font-size: 9pt;
        line-height: 1.45;
        color: #1e293b;
        margin: 0;
        padding: 0;
    }}
    .doc-title, h1.doc-title {{
        font-size: 14pt;
        font-weight: 700;
        text-align: center;
        color: #0f172a;
        margin: 10pt 0 12pt 0;
        letter-spacing: 0.5pt;
    }}
    .doc-chapter, h2.doc-chapter {{
        font-size: 11.5pt;
        font-weight: 700;
        text-align: center;
        color: #0f172a;
        margin: 13pt 0 5pt 0;
        letter-spacing: 0.3pt;
    }}
    .doc-section, h3.doc-section {{
        font-size: 10pt;
        font-weight: 600;
        text-align: center;
        color: #1e293b;
        margin: 8pt 0 4pt 0;
    }}
    .doc-article-title, h4.doc-article-title {{
        font-size: 9.5pt;
        font-weight: 700;
        color: #0f172a;
        margin: 8pt 0 3pt 0;
    }}
    .doc-subheading, h5.doc-subheading {{
        font-size: 9pt;
        font-weight: 700;
        color: #1e293b;
        margin: 6pt 0 2pt 0;
    }}
    .doc-clause {{
        margin: 3.5pt 0 3.5pt 20pt;
        text-indent: -20pt;
        text-align: justify;
        line-height: 1.45;
    }}
    .doc-clause b {{
        font-weight: 700;
        color: #0f172a;
    }}
    .doc-item {{
        margin: 2.5pt 0 2.5pt 24pt;
        text-indent: -16pt;
        text-align: justify;
        line-height: 1.42;
    }}
    .doc-item b {{
        font-weight: 600;
        color: #0f172a;
    }}
    .doc-subitem {{
        margin: 2.5pt 0 2.5pt 36pt;
        text-indent: -16pt;
        text-align: justify;
        line-height: 1.42;
    }}
    .doc-subitem b {{
        font-weight: 600;
        color: #0f172a;
    }}
    .doc-subitem-desc {{
        margin: 1.5pt 0 3pt 36pt;
        text-align: justify;
        line-height: 1.42;
    }}
    .doc-bullet-item {{
        margin: 2.5pt 0 2.5pt 24pt;
        text-indent: -14pt;
        text-align: justify;
        line-height: 1.42;
    }}
    .doc-bullet-item .bullet {{
        font-weight: bold;
        color: #0f172a;
        display: inline-block;
        width: 14pt;
    }}
    .doc-sub-bullet {{
        margin: 2pt 0 2pt 48pt;
        text-indent: -14pt;
        text-align: justify;
        line-height: 1.42;
    }}
    .doc-sub-bullet .bullet {{
        font-weight: bold;
        color: #0f172a;
        display: inline-block;
        width: 14pt;
    }}
    .doc-paragraph, p {{
        margin: 3.5pt 0;
        text-align: justify;
        line-height: 1.45;
    }}
    .doc-tree {{
        font-family: Consolas, Monaco, monospace;
        font-size: 8.5pt;
        line-height: 1.35;
        background: #f8fafc;
        border: 0.5pt solid #e2e8f0;
        border-radius: 4pt;
        padding: 5pt 8pt;
        margin: 5pt 0;
        color: #1e293b;
        white-space: pre;
    }}
    /* Dynamic Dot-Leader Table of Contents */
    .toc-container {{
        width: 100%;
        margin-top: 4pt;
    }}
    .toc-table {{
        width: 100%;
        border-collapse: collapse;
        border: none !important;
    }}
    .toc-table td {{
        border: none !important;
        padding: 2.5pt 0;
        vertical-align: bottom;
    }}
    .toc-row.level-0 .toc-title {{
        font-weight: 700;
        font-size: 9.5pt;
        color: #0f172a;
        padding-top: 7pt;
    }}
    .toc-row.level-1 .toc-title {{
        padding-left: 14pt;
        font-weight: 600;
        font-size: 9pt;
        color: #1e293b;
        padding-top: 3.5pt;
    }}
    .toc-row.level-2 .toc-title {{
        padding-left: 24pt;
        font-size: 8.5pt;
        color: #334155;
    }}
    .toc-row.level-3 .toc-title {{
        padding-left: 36pt;
        font-size: 8.5pt;
        color: #475569;
    }}
    .toc-leader {{
        width: 100%;
        padding: 0 4pt !important;
        border: none !important;
    }}
    .toc-leader .dots {{
        border-bottom: 1.2pt dotted #94a3b8;
        height: 1em;
        width: 100%;
    }}
    .toc-page {{
        text-align: right;
        width: 32pt;
        font-weight: 600;
        font-size: 9pt;
        color: #1e293b;
        white-space: nowrap;
        border: none !important;
    }}
    /* Standard Tables & Complex HTML Tables */
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 5pt 0;
        font-size: 8.5pt;
        table-layout: auto;
        word-wrap: break-word;
        direction: ltr;
        writing-mode: horizontal-tb;
        transform: none;
    }}
    th, td {{
        border: 0.5pt solid #cbd5e1;
        padding: 3.5pt 5.5pt;
        text-align: left;
        vertical-align: top;
    }}
    th {{
        background-color: #f1f5f9;
        font-weight: 700;
        color: #0f172a;
    }}
    thead th {{
        background-color: #f1f5f9;
        text-align: center;
        vertical-align: middle;
    }}
    td[colspan], th[colspan], td[rowspan], th[rowspan] {{
        border: 0.5pt solid #cbd5e1;
    }}
    tr:nth-child(even) td {{
        background-color: #f8fafc;
    }}
    /* Borderless Tables for Key-Value & Aligned 2-Column Lists */
    table.borderless, table.borderless td, table.borderless th {{
        border: none !important;
        padding: 2pt 6pt;
        background-color: transparent !important;
    }}
    table.borderless tr:nth-child(even) td {{
        background-color: transparent !important;
    }}
    /* Wide / Dense Tables (8+ columns) */
    table.dense {{
        font-size: 7pt !important;
        margin: 4pt 0;
    }}
    table.dense th, table.dense td {{
        padding: 2pt 2.5pt !important;
        text-align: center;
    }}
    table.dense th:first-child, table.dense td:first-child {{
        text-align: left;
    }}
    /* Mathematical Formula Tables */
    table.formula-table {{
        margin: 6pt auto;
        border-collapse: collapse;
        border: none !important;
    }}
    table.formula-table td {{
        border: none !important;
        background-color: transparent !important;
        line-height: 1.35;
    }}
    table.formula-table tr:nth-child(even) td {{
        background-color: transparent !important;
    }}
    /* Stamp Box */
    .stamp-table {{
        margin-left: auto;
        margin-right: 8pt;
        margin-top: 6pt;
        margin-bottom: 6pt;
        border: 1.5pt solid #dc2626;
        border-radius: 4pt;
        color: #dc2626;
        font-size: 8pt;
        font-weight: bold;
        text-align: center;
        width: auto;
    }}
    .stamp-table td {{
        padding: 4pt 8pt;
        border: none;
        line-height: 1.35;
    }}
    .page-footer {{
        text-align: center;
        font-size: 8.5pt;
        color: #64748b;
        margin-top: 14pt;
    }}
    """


def is_cover_page_content(text: str) -> bool:
    """
    Determines if text represents a cover / title page.
    Criteria: short text without chapter/article/clause divisions, without numbered lists or tabular pipes,
    representing a standalone document cover or title page layout.
    """
    clean = re.sub(r'\[(?:Stamp|Seal|Approved):\s*[\s\S]*?\]', '', text, flags=re.I).strip()
    if re.search(r'<(?:table|ul|ol)\b', clean, re.I):
        return False
    lines = [l.strip() for l in clean.splitlines() if l.strip()]
    if 1 <= len(lines) <= 6 and len(clean) < 350:
        # Cover pages do not have internal chapters, sections, articles, or sub-headings
        if not re.search(r'\b(?:Chapter|Article|Section|\d+[A-Za-z]?(?:\.\d+)+)\b', clean, re.I):
            if not re.search(r'^\s*#{2,}', clean, re.M):
                if not re.search(r'^\s*(?:[①-⑳]|\(\d+\)|\d+[.)、]|\d+\s+\S)', clean, re.M):
                    if not re.search(r'\|.*\|', clean):
                        return True
    return False


def is_toc_page_content(text: str) -> bool:
    """
    Determines if text represents a Table of Contents page across languages and formats.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip() and not re.match(r'^\s*```', l)]
    if not lines:
        return False
    # Check title across common languages (English, Japanese, Korean, Chinese, French, German, Spanish)
    toc_pattern = r'^(?:#+\s*)?(?:Table\s+of\s+Contents|Contents|目次|목차|目录|Sommaire|Inhalt|Indice|Tabla\s+de\s+contenidos)\b'
    if any(re.match(toc_pattern, l, re.I) for l in lines[:3]):
        return True
    # Count lines that look like TOC entries (entry title followed by leader dots or spaces and page number)
    count_toc = 0
    for l in lines:
        if re.search(r'[·\.\s]{2,}\s*\d+$', l):
            count_toc += 1
        elif re.match(r'^(?:#+\s*)?(?:Chapter|Section|Article|Part|Chapitre|Kapitel|Capítulo|Capitolo|Appended|Supplementary|第\s*\d+\s*[章節条部]|제\s*\d+\s*[장절조])\b', l, re.I):
            count_toc += 1
    return count_toc >= 4 and count_toc / max(len(lines), 1) > 0.35


def render_toc_page_html(lines: List[str], page_num: Optional[int] = None) -> str:
    """
    Renders lines of Table of Contents into a robust 2-column dot-leader table with
    hierarchical indentation and right-aligned page numbers.
    Uses borderless inline styles with dynamic dot leaders trailing the title
    to guarantee clean rendering across all PDF engines without bounding gaps or misalignments.
    """
    html_out: List[str] = []
    start_idx = 0
    toc_pattern = r'^(?:#+\s*)?(?:Table\s+of\s+Contents|Contents|目次|목차|目录|Sommaire|Inhalt|Indice|Tabla\s+de\s+contenidos)\b'
    if lines and re.match(toc_pattern, lines[0].strip(), re.I):
        title_text = re.sub(r"^#+\s*", "", lines[0].strip()).strip()
        html_out.append(f'<div class="doc-title">{title_text}</div>')
        start_idx = 1

    # Pre-process lines: merge orphan page numbers into previous line
    merged_lines: List[str] = []
    for raw_line in lines[start_idx:]:
        l = raw_line.strip()
        if not l or re.match(r'^\s*```', l):
            continue
        if re.match(r'^\d+$', l):
            if merged_lines:
                merged_lines[-1] = f"{merged_lines[-1]} ··· {l}"
            continue
        # Preserve leading whitespace count from raw_line for indentation detection
        merged_lines.append(raw_line)

    html_out.append('<div class="toc-container"><table class="toc-table" style="width: 100%; border-collapse: collapse; border: none !important; margin: 0;">')
    for raw_line in merged_lines:
        l = raw_line.strip()
        leading_spaces = len(raw_line) - len(raw_line.lstrip())

        # Extract trailing page number preceded by at least two separator characters (dots, spaces, tabs)
        m_page = re.search(r'(?:[·\.]{2,}|\s{2,}|\t+)\s*(\d+)$', l)
        if not m_page:
            # Fallback: single bullet/dot with space e.g. " · 4" or trailing space + digits
            m_page = re.search(r'\s+[·\.\-]\s*(\d+)$', l)

        page_str = m_page.group(1) if m_page else ""
        title_part = l[:m_page.start()].strip() if m_page else l
        title_part = re.sub(r'[\s·\.\-—_]+$', '', title_part).strip()

        # Determine level for hierarchical indentation
        level = 2
        m_h = re.match(r'^(#{1,6})\s*', title_part)
        if m_h:
            h_len = len(m_h.group(1))
            if h_len <= 2:
                level = 0
            elif h_len == 3:
                level = 1
            else:
                level = 2
        elif leading_spaces >= 6:
            level = 3
        elif leading_spaces >= 4:
            level = 2
        elif leading_spaces >= 2:
            level = 1
        elif re.match(r'^(?:Chapter|Part|CHAPTER|PART|Chapitre|Kapitel|Capítulo|Capitolo|第\s*\d+\s*章|제\s*\d+\s*장|Appended\s+Table|Appended|Supplementary)', title_part, re.I):
            level = 0
        elif re.match(r'^(?:Section|SECTION|第\s*\d+\s*節|제\s*\d+\s*절)', title_part, re.I):
            level = 1
        elif re.match(r'^(?:Article|ARTICLE|第\s*\d+\s*条|제\s*\d+\s*조)', title_part, re.I):
            level = 2
        else:
            level = 2

        # Strip any leading markdown heading hashes and bold/italic markers
        clean_title = re.sub(r'^#+\s*', '', title_part).strip()
        clean_title = re.sub(r'[*_`]', '', clean_title).strip()

        # Configure indentation and typography per hierarchy level
        if level == 0:
            pad_left = 0
            pad_top = 7
            pad_bottom = 2.5
            font_css = "font-weight: 700; font-size: 9.5pt; color: #0f172a;"
        elif level == 1:
            pad_left = 14
            pad_top = 4
            pad_bottom = 2
            font_css = "font-weight: 600; font-size: 9pt; color: #1e293b;"
        elif level == 2:
            pad_left = 26
            pad_top = 1.5
            pad_bottom = 1.5
            font_css = "font-weight: 400; font-size: 8.5pt; color: #334155;"
        else:
            pad_left = 38
            pad_top = 1
            pad_bottom = 1
            font_css = "font-weight: 400; font-size: 8pt; color: #475569;"

        if page_str:
            num_dots = max(10, min(65, 80 - len(clean_title) * 3 // 2))
            dots = "·" * num_dots
            html_out.append(
                f'<tr style="border: none !important;">'
                f'<td class="toc-entry" style="border: none !important; padding: {pad_top}pt 0 {pad_bottom}pt {pad_left}pt; {font_css} vertical-align: bottom;">'
                f'{clean_title} <span class="toc-dots" style="color: #94a3b8; font-size: 7.5pt; letter-spacing: 2px;">{dots}</span>'
                f'</td>'
                f'<td class="toc-page-num" style="border: none !important; text-align: right; width: 28pt; white-space: nowrap; font-weight: 600; font-size: 8.5pt; color: #0f172a; vertical-align: bottom; padding: {pad_top}pt 0 {pad_bottom}pt 0;">'
                f'{page_str}'
                f'</td>'
                f'</tr>'
            )
        else:
            html_out.append(
                f'<tr style="border: none !important;">'
                f'<td colspan="2" class="toc-entry" style="border: none !important; padding: {pad_top}pt 0 {pad_bottom}pt {pad_left}pt; {font_css} vertical-align: bottom;">'
                f'{clean_title}'
                f'</td>'
                f'</tr>'
            )
    html_out.append('</table></div>')
    if page_num:
        html_out.append(f'<div class="page-footer">{page_num}</div>')
    return "\n".join(html_out)


def render_cover_page_html(text: str) -> str:
    """
    Renders cover page layout with centered title, date, and official stamp table.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = lines[0] if lines else "Document"
    title = re.sub(r'^#+\s*', '', title)
    remaining = lines[1:] if len(lines) > 1 else []

    date_text = ""
    stamps_html = ""
    for r in remaining:
        if '<table class="stamp-table"' in r or '[Stamp:' in r or '[Seal:' in r:
            m_st = re.search(r'\[(?:Stamp|Seal|Approved):\s*([\s\S]*?)\]', r, re.I)
            if m_st:
                content = m_st.group(1).strip().replace('\n', '<br>')
                stamps_html += f'<table class="stamp-table"><tr><td>{content}</td></tr></table>'
            elif '<table class="stamp-table"' in r:
                stamps_html += r
        else:
            date_text += f'<div class="cover-date">{r}</div>'

    return f"""
    <div class="cover-title">{title}</div>
    {date_text}
    <div class="cover-stamp-container">{stamps_html}</div>
    """


def sanitize_text(text: str) -> str:
    """
    Sanitizes raw text to prevent MuPDF HTML parser crashes.
    Replaces null bytes (\x00) with bullet characters and strips non-printable control chars.
    """
    if not text:
        return ""
    # Replace null bytes that terminate C-strings in MuPDF
    text = text.replace('\x00', '• ')
    clean_chars = []
    for c in text:
        if ord(c) < 32 and c not in ('\n', '\r', '\t'):
            clean_chars.append(' ')
        else:
            clean_chars.append(c)
    return "".join(clean_chars)




def convert_latex_math_to_html(text: str) -> str:
    """
    Universally converts LaTeX math expressions and fractions into publication-grade HTML
    division fraction tables or formatted equations compatible with PyMuPDF.
    """
    if not text or ("\\frac" not in text and "$$" not in text):
        return text

    def clean_math_text(s: str) -> str:
        s = re.sub(r'\\text\{([^}]+)\}', r'\1', s)
        s = re.sub(r'\\mathrm\{([^}]+)\}', r'\1', s)
        s = re.sub(r'\\times', '×', s)
        s = re.sub(r'\\div', '÷', s)
        s = re.sub(r'\\pm', '±', s)
        s = s.replace('$$', '').replace('$', '').strip()
        return s

    # Pattern 1: Variable = \frac{Numerator}{Denominator} (with or without $$)
    def replace_eq_frac(m):
        raw_var = m.group(1).strip()
        num = clean_math_text(m.group(2))
        denom = clean_math_text(m.group(3))
        var = clean_math_text(raw_var)
        return (
            f'\n<table class="formula-table" style="margin: 8pt auto; border-collapse: collapse; border: none;">'
            f'<tr>'
            f'<td style="border: none !important; vertical-align: bottom; text-align: right; padding: 2pt 8pt 2pt 0; font-weight: 600; font-size: 8.5pt; white-space: nowrap;">{var} =</td>'
            f'<td style="border: none !important; border-bottom: 1.5pt solid #0f172a !important; padding: 2pt 8pt; font-size: 8pt; text-align: center; vertical-align: bottom;">{num}</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="border: none !important; padding: 0;"></td>'
            f'<td style="border: none !important; padding: 2pt 8pt; font-size: 8pt; text-align: center; vertical-align: top;">{denom}</td>'
            f'</tr>'
            f'</table>\n'
        )

    pattern_eq = re.compile(
        r'(?:\$\$|\$)?\s*([^\n=]+?)\s*=\s*\\frac\{((?:[^{}]|\{[^{}]*\})+)\}\{((?:[^{}]|\{[^{}]*\})+)\}\s*(?:\$\$|\$)?',
        re.DOTALL
    )
    text = pattern_eq.sub(replace_eq_frac, text)

    # Pattern 2: Standalone \frac{Numerator}{Denominator} without variable
    def replace_standalone_frac(m):
        num = clean_math_text(m.group(1))
        denom = clean_math_text(m.group(2))
        return (
            f'\n<table class="formula-table" style="margin: 6pt auto; border-collapse: collapse; border: none; text-align: center; display: inline-table;">'
            f'<tr>'
            f'<td style="border: none; border-bottom: 1pt solid #0f172a; padding: 2pt 6pt; font-size: 8pt; text-align: center;">{num}</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="border: none; padding: 2pt 6pt; font-size: 8pt; text-align: center;">{denom}</td>'
            f'</tr>'
            f'</table>\n'
        )

    pattern_standalone = re.compile(
        r'(?:\$\$|\$)?\s*\\frac\{((?:[^{}]|\{[^{}]*\})+)\}\{((?:[^{}]|\{[^{}]*\})+)\}\s*(?:\$\$|\$)?',
        re.DOTALL
    )
    text = pattern_standalone.sub(replace_standalone_frac, text)

    # Clean any residual $$ or \text{}
    text = re.sub(r'\$\$(.*?)\$\$', lambda m: clean_math_text(m.group(1)), text, flags=re.DOTALL)
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)

    return text


def normalize_markdown_content(md_text: str) -> Tuple[str, bool, Optional[int]]:
    """
    Normalizes translated markdown content:
    1. Sanitizes null bytes (\x00) and control characters.
    2. Converts LaTeX math expressions and formulas to clean HTML fraction tables.
    3. Detects cover page.
    4. Extracts footer page numbers.
    5. Converts [Stamp: ...] tags into structured stamp table markup.
    6. Filters stray code fence lines (```).
    7. Strips spurious bullet markers prepended to clauses or numbers.
    """
    if not md_text:
        return "", False, None

    text = sanitize_text(md_text).strip()
    is_cover = False
    page_num = None

    # Step 0: Convert LaTeX math and formulas to HTML division tables
    text = convert_latex_math_to_html(text)

    # Step 1: Detect footer page number
    lines = text.splitlines()
    if lines:
        last_line = lines[-1].strip()
        footer_match = re.match(r'^(?:\[Page:\s*(\d+)\]|Page\s+(\d+)|\b(\d+)\b)$', last_line, re.I)
        if footer_match:
            try:
                num_str = next(g for g in footer_match.groups() if g is not None)
                page_num = int(num_str)
                lines.pop()
                text = "\n".join(lines)
            except (StopIteration, ValueError):
                pass

    # Step 2: Detect Cover Page
    if is_cover_page_content(text):
        is_cover = True

    # Step 3: Convert stamps
    def replace_stamp(match):
        stamp_content = match.group(1).strip()
        stamp_content = re.sub(r'^(?:Stamp|Seal|Approved|Received):\s*', '', stamp_content, flags=re.IGNORECASE)
        parts = [p.strip() for p in re.split(r'[,;\n]\s*', stamp_content) if p.strip()]
        formatted_content = "<br>".join(parts) if parts else stamp_content
        return f'<table class="stamp-table"><tr><td>{formatted_content}</td></tr></table>'

    text = re.sub(r'\[(?:Stamp|Seal|Approved):\s*([\s\S]*?)\]', replace_stamp, text, flags=re.IGNORECASE)

    # Step 4: Discard standalone code fences & strip spurious bullets before numbered / decimal clauses
    cleaned_lines = []
    for line in text.splitlines():
        if re.match(r'^\s*```(?:markdown|html|[a-zA-Z0-9_-]+)?\s*$', line):
            continue
        # Only strip spurious bullets prepended to decimal clauses (• 4.1), numbered lists (• 1. ), or headings (• #)
        # NEVER strip indented bullets (subordinates) or bullets with general text (• Article 35...)
        if not re.match(r'^\s{2,}', line):
            subbed = re.sub(r'^[\*\-\•]\s+(?=(?:\d+\.\d+\b|\d+\.\s+|[①-⑳]\s*#|#+))', '', line)
        else:
            subbed = line
        cleaned_lines.append(subbed)
    text = "\n".join(cleaned_lines)

    return text, is_cover, page_num


def parse_pipe_table(lines: List[str]) -> str:
    """
    Parses a block of lines containing markdown/pipe tables.
    Normalizes column counts across all rows, preserves empty cells cleanly,
    and ensures positional column invariance (e.g. sub-items missing item number).
    """
    if not lines:
        return ""

    raw_rows: List[Tuple[int, List[str]]] = []  # (original_idx, cells)
    delim_idx = -1

    for idx, l in enumerate(lines):
        if re.match(r'^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$', l):
            delim_idx = idx
            continue
        cleaned = l.strip()
        if not cleaned:
            continue
        if cleaned.startswith("|"):
            cleaned = cleaned[1:]
        if cleaned.endswith("|"):
            cleaned = cleaned[:-1]
        cells = [c.strip() for c in cleaned.split("|")]
        raw_rows.append((idx, cells))

    if not raw_rows:
        return "\n".join(lines)

    max_cols = max(len(cells) for _, cells in raw_rows)
    if max_cols <= 0:
        return "\n".join(lines)

    rows_html: List[str] = []
    for idx, cells in raw_rows:
        tag = "th" if (delim_idx > 0 and idx < delim_idx) else "td"
        num_cells = len(cells)

        # Handle ragged rows (missing cells)
        if num_cells < max_cols:
            first_txt = cells[0] if cells else ""
            first_is_num = bool(re.match(r'^\d+[\.\)]?$', first_txt))
            # If table has a numeric item sequence in column 0 and this row starts with non-numeric text,
            # the missing cell belongs at column 0 (e.g. sub-conditions in Article 39.1).
            if not first_is_num and num_cells == max_cols - 1:
                cells = [""] + cells
            else:
                cells = cells + [""] * (max_cols - num_cells)

        cell_tags: List[str] = []
        for c in cells:
            c_rend = markdown.markdown(c).replace("<p>", "").replace("</p>", "").strip() if c else ""
            cell_tags.append(f"<{tag}>{c_rend}</{tag}>")

        rows_html.append(f"<tr>{''.join(cell_tags)}</tr>")

    table_class = ' class="dense"' if max_cols >= 8 else ''
    return f"<table{table_class}><tbody>{''.join(rows_html)}</tbody></table>"


def flatten_multitier_table_html(html_str: str) -> str:
    """
    Transforms multi-tier HTML tables with rowspan/colspan in <thead> or ragged <tbody>
    into unified 1-to-1 column tables compatible with PyMuPDF story layout.
    """
    if "<table" not in html_str.lower():
        return html_str

    try:
        soup = BeautifulSoup(html_str, "html.parser")
    except Exception:
        return html_str

    tables = soup.find_all("table")
    if not tables:
        return html_str

    for table in tables:
        cls_list = table.get("class", [])
        if "formula-table" in cls_list or "borderless" in cls_list:
            continue

        thead = table.find("thead")
        tbody = table.find("tbody")

        all_trs = table.find_all("tr")
        header_rows = thead.find_all("tr") if thead else []
        if not header_rows and all_trs:
            for r in all_trs:
                if r.find("th"):
                    header_rows.append(r)
                else:
                    break

        body_rows = tbody.find_all("tr") if tbody else [r for r in all_trs if r not in header_rows]
        if not body_rows and not header_rows:
            continue

        max_cols = 0
        for r in body_rows:
            cols = sum(int(c.get("colspan", 1)) for c in r.find_all(["td", "th"]))
            if cols > max_cols:
                max_cols = cols
        for r in header_rows:
            cols = sum(int(c.get("colspan", 1)) for c in r.find_all(["td", "th"]))
            if cols > max_cols:
                max_cols = cols

        if max_cols <= 0:
            continue

        # 1. Process Multi-tier Header if present
        if len(header_rows) > 1:
            grid = [[None] * max_cols for _ in range(len(header_rows))]
            for r_idx, row in enumerate(header_rows):
                c_idx = 0
                for cell in row.find_all(["th", "td"]):
                    while c_idx < max_cols and grid[r_idx][c_idx] is not None:
                        c_idx += 1
                    if c_idx >= max_cols:
                        break
                    rowspan = int(cell.get("rowspan", 1))
                    colspan = int(cell.get("colspan", 1))
                    text = cell.get_text(separator=" ", strip=True)
                    for r in range(r_idx, min(r_idx + rowspan, len(header_rows))):
                        for c in range(c_idx, min(c_idx + colspan, max_cols)):
                            grid[r][c] = text
                    c_idx += colspan

            # Identify if row 0 has a wide parent category spanning >= 3 sub-columns
            row0_spans = {}
            if len(header_rows) >= 2:
                cur_val = None
                start_c = 0
                for c in range(max_cols):
                    v = grid[0][c]
                    if v != cur_val:
                        if cur_val and (c - start_c) >= 3:
                            row0_spans[cur_val] = (start_c, c)
                        cur_val = v
                        start_c = c
                if cur_val and (max_cols - start_c) >= 3:
                    row0_spans[cur_val] = (start_c, max_cols)

            composite_headers = []
            for c in range(max_cols):
                labels = []
                for r in range(len(header_rows)):
                    lbl = grid[r][c]
                    if lbl and (not labels or lbl != labels[-1]):
                        labels.append(lbl)

                # If the top label is a wide-spanning category (>=3 columns), don't repeat it in sub-column headers
                if labels and labels[0] in row0_spans:
                    span_start, span_end = row0_spans[labels[0]]
                    if span_start > 0 and c >= span_start:
                        if len(labels) > 1:
                            labels = labels[1:]  # Keep only concise sub-column label (e.g. date range)

                if not labels:
                    composite_headers.append("")
                elif len(labels) == 1:
                    composite_headers.append(labels[0])
                elif len(labels) == 2:
                    composite_headers.append(f"{labels[0]}<br>({labels[1]})")
                else:
                    composite_headers.append(f"{labels[0]}: {labels[1]}<br>({labels[2]})")

            # If row 0 had wide parent categories and Column 0 exists, merge the parent category into Column 0
            if row0_spans and len(composite_headers) > 0:
                for wide_cat, (s_c, e_c) in row0_spans.items():
                    if s_c > 0 and wide_cat not in composite_headers[0]:
                        if composite_headers[0]:
                            composite_headers[0] = f"{wide_cat} &amp;<br>{composite_headers[0]}"
                        else:
                            composite_headers[0] = wide_cat

            if thead:
                thead.clear()
            else:
                thead = soup.new_tag("thead")
                table.insert(0, thead)

            new_tr = soup.new_tag("tr")
            for h in composite_headers:
                th = soup.new_tag("th")
                sub_soup = BeautifulSoup(h, "html.parser")
                for child in list(sub_soup.contents):
                    th.append(child)
                new_tr.append(th)
            thead.append(new_tr)

            for hr in header_rows:
                if hr.parent != thead:
                    hr.decompose()

        # Check if wide matrix table (>6 cols) has trailing merged rows (e.g. notes or single values spanning all data cols)
        trailing_start = len(body_rows)
        if max_cols >= 7 and len(body_rows) >= 2:
            for idx in range(len(body_rows) - 1, -1, -1):
                r = body_rows[idx]
                r_cells = r.find_all(["td", "th"])
                is_merged = False
                if len(r_cells) == 1:
                    is_merged = True
                elif len(r_cells) == 2:
                    colspan = int(r_cells[1].get("colspan", 1))
                    txt = r_cells[1].get_text(strip=True)
                    if colspan >= 4 or len(txt) > 20:
                        is_merged = True
                elif len(r_cells) >= 6:
                    texts = [c.get_text(strip=True) for c in r_cells]
                    if len(set(texts[1:])) == 1 and texts[1]:
                        if len(texts[1]) > 20 or (idx > 0 and any(len(next_r.find_all(["td", "th"])) <= 2 for next_r in body_rows[idx + 1:])):
                            is_merged = True

                if is_merged:
                    trailing_start = idx
                else:
                    break

        # If trailing merged rows found, split into two contiguous seamless tables
        if 0 < trailing_start < len(body_rows) and max_cols >= 7:
            grid_rows = body_rows[:trailing_start]
            trailing_rows = body_rows[trailing_start:]

            col0_pct = 18
            table["style"] = "width: 100%; border-collapse: collapse; margin-bottom: 0; font-size: 6pt; table-layout: fixed;"
            # Apply fixed widths to first header or grid row
            first_row = thead.find("tr") if thead else (grid_rows[0] if grid_rows else None)
            if first_row:
                f_cells = first_row.find_all(["th", "td"])
                if f_cells:
                    f_cells[0]["style"] = (f_cells[0].get("style", "") + f"; width: {col0_pct}%;").strip("; ")
                    rem_w = (100 - col0_pct) / max(len(f_cells) - 1, 1)
                    for fc in f_cells[1:]:
                        fc["style"] = (fc.get("style", "") + f"; width: {rem_w:.1f}%;").strip("; ")

            # Build Table 2 (Merged trailing rows)
            table2 = soup.new_tag("table")
            table2["style"] = "width: 100%; border-collapse: collapse; margin-top: -0.5pt; font-size: 6pt; table-layout: fixed;"
            t2_body = soup.new_tag("tbody")
            table2.append(t2_body)

            for tr in trailing_rows:
                tr.extract()
                cells = tr.find_all(["td", "th"])
                new_tr = soup.new_tag("tr")
                if len(cells) == 1:
                    c = cells[0]
                    c["colspan"] = "2"
                    c["style"] = "width: 100%; text-align: left; padding: 2.5pt 4pt; border: 0.5pt solid #cbd5e1;"
                    new_tr.append(c)
                elif len(cells) >= 2:
                    lbl_c = cells[0]
                    lbl_c["style"] = f"width: {col0_pct}%; text-align: left; padding: 2.5pt 3pt; font-weight: 600; border: 0.5pt solid #cbd5e1;"
                    new_tr.append(lbl_c)

                    val_c = soup.new_tag("td")
                    texts = [c.get_text(strip=True) for c in cells[1:]]
                    val_txt = texts[0] if texts else ""
                    val_c.string = val_txt
                    val_c["style"] = f"width: {100 - col0_pct}%; padding: 2.5pt 4pt; border: 0.5pt solid #cbd5e1;"
                    if len(val_txt) <= 6:
                        val_c["style"] += " text-align: center;"
                    else:
                        val_c["style"] += " text-align: left;"
                    new_tr.append(val_c)
                t2_body.append(new_tr)

            table.insert_after(table2)
            body_rows = grid_rows

        # 2. Process Body Rows with colspan and merged columns
        for r in body_rows:
            cells = r.find_all(["td", "th"])

            # Detect rows where all data columns have identical repeated values
            # (e.g. when an upstream converter or generator duplicated a single merged cell across columns)
            if len(cells) >= 6:
                texts = [c.get_text(strip=True) for c in cells]
                if len(set(texts[1:])) == 1 and texts[1]:
                    shared_txt = texts[1]
                    data_span = len(cells) - 1
                    if len(shared_txt) <= 6:
                        mid_idx = 1 + data_span // 2
                        for idx, c in enumerate(cells[1:], start=1):
                            c.clear()
                            is_start = (idx == 1)
                            is_end = (idx == len(cells) - 1)
                            cur_style = c.get("style", "")
                            if is_start:
                                c["style"] = (cur_style + "; border-right: none !important;").strip("; ")
                            elif is_end:
                                c["style"] = (cur_style + "; border-left: none !important;").strip("; ")
                            else:
                                c["style"] = (cur_style + "; border-left: none !important; border-right: none !important;").strip("; ")
                            if idx == mid_idx:
                                c.string = shared_txt
                                c["style"] = (c["style"] + "; text-align: center; font-weight: inherit;").strip("; ")
                    else:
                        cells[1].string = shared_txt
                        c1_style = cells[1].get("style", "")
                        cells[1]["style"] = (c1_style + "; border-right: none !important; text-align: left; padding-left: 4pt;").strip("; ")
                        for idx, c in enumerate(cells[2:], start=2):
                            c.clear()
                            is_end = (idx == len(cells) - 1)
                            r_border = "" if is_end else " border-right: none !important;"
                            c_style = c.get("style", "")
                            c["style"] = (c_style + f"; border-left: none !important;{r_border}").strip("; ")
                    continue

            new_cells = []
            for cell in cells:
                colspan = int(cell.get("colspan", 1))
                if colspan > 1:
                    txt = cell.get_text(strip=True)
                    del cell["colspan"]
                    existing_style = cell.get("style", "")
                    clean_base = "; ".join([p.strip() for p in existing_style.split(";") if p.strip()])

                    if len(txt) <= 6:
                        # Short value (number, code, abbreviation): center in middle cell of the span
                        mid_offset = colspan // 2
                        cell.clear()
                        cell["style"] = (clean_base + "; border-right: none !important;").strip("; ")
                        new_cells.append(cell)
                        for i_span in range(1, colspan):
                            span_c = soup.new_tag("td")
                            is_last = (i_span == colspan - 1)
                            r_border = "" if is_last else " border-right: none !important;"
                            span_c["style"] = f"border-left: none !important;{r_border}".strip("; ")
                            if i_span == mid_offset and txt:
                                span_c.string = txt
                                span_c["style"] = (span_c["style"] + "; text-align: center; font-weight: inherit;").strip("; ")
                            new_cells.append(span_c)
                    else:
                        # Longer text / notes: place in the first cell, subsequent cells empty
                        cell.string = txt
                        cell["style"] = (clean_base + "; border-right: none !important; text-align: left; padding-left: 4pt;").strip("; ")
                        new_cells.append(cell)
                        for i_span in range(1, colspan):
                            empty_c = soup.new_tag("td")
                            is_last = (i_span == colspan - 1)
                            r_border = "" if is_last else " border-right: none !important;"
                            empty_c["style"] = f"border-left: none !important;{r_border}".strip("; ")
                            new_cells.append(empty_c)
                else:
                    new_cells.append(cell)

            if len(new_cells) < max_cols:
                first_txt = new_cells[0].get_text(strip=True) if new_cells else ""
                first_is_num = bool(re.match(r'^\d+[\.\)]?$', first_txt))
                if not first_is_num and len(new_cells) == max_cols - 1:
                    pad = soup.new_tag("td")
                    new_cells = [pad] + new_cells
                else:
                    while len(new_cells) < max_cols:
                        new_cells.append(soup.new_tag("td"))

            r.clear()
            for c in new_cells:
                r.append(c)

        existing_classes = table.get("class", [])
        if max_cols >= 8 and "dense" not in existing_classes:
            table["class"] = existing_classes + ["dense"]

    return str(soup)


def render_markdown_to_html(md_text: str, target_lang: str = "English", is_toc: Optional[bool] = None) -> str:
    """
    Renders normalized markdown to complete HTML with embedded CSS and layout styling.
    Ensures:
    - Dedicated cover page centering and styling.
    - Hierarchical Table of Contents with dynamic dotted leaders and right-aligned page numbers.
    - Centered Chapter and Section headings with clear vertical margins.
    - Bold Article titles with proper spacing.
    - Hanging indents on decimal clauses (4.1, 4.2), numbered lists (1., 2.), and circled items (①, ②).
    - Preserved Markdown tables, HTML tables with colspan/rowspan, and preformatted ASCII branch diagrams.
    - Justified body text and line break preservation.
    """
    cleaned_md, is_cover, page_num = normalize_markdown_content(md_text)

    # Handle Cover Page
    if is_cover:
        css = build_document_css(target_lang=target_lang, is_cover=True)
        body_html = render_cover_page_html(cleaned_md)
        return f"<!DOCTYPE html><html><head><style>{css}</style></head><body>{body_html}</body></html>"

    # Handle Table of Contents
    if (is_toc is True) or (is_toc is None and is_toc_page_content(cleaned_md)):
        css = build_document_css(target_lang=target_lang, is_cover=False)
        body_html = render_toc_page_html(cleaned_md.splitlines(), page_num=page_num)
        return f"<!DOCTYPE html><html><head><style>{css}</style></head><body>{body_html}</body></html>"

    # Standard Document Body Page
    css = build_document_css(target_lang=target_lang, is_cover=False)

    body_blocks: List[str] = []
    in_table = False
    table_lines: List[str] = []
    in_tree = False
    tree_lines: List[str] = []

    def flush_table():
        nonlocal in_table, table_lines
        if table_lines:
            tbl_html = parse_pipe_table(table_lines)
            body_blocks.append(tbl_html)
            table_lines = []
        in_table = False

    def flush_tree():
        nonlocal in_tree, tree_lines
        if tree_lines:
            content = "\n".join(tree_lines)
            body_blocks.append(f'<div class="doc-tree">{content}</div>')
            tree_lines = []
        in_tree = False

    last_block_type = ""
    stop_pattern = re.compile(
        r'^(?:\d+[A-Za-z]?(?:\.\d+)+|\d+[.)、]|\d+\s+\S|Article|Chapter|Section|[①-⑳]|\(\d+\)|[•\*\-▪▫○·]|\||#+)',
        re.I
    )
    kv_pattern = re.compile(r'^[^\n:]{2,50}\s*:\s*[^\n]+$')

    def is_continuation_line(curr_line: str, next_line: str) -> bool:
        """Determines if next_line is a pure prose continuation of curr_line."""
        if not next_line or not next_line.strip():
            return False
        n_strip = next_line.strip()
        c_strip = curr_line.strip()
        if c_strip.endswith(":"):
            return False
        if curr_line.endswith("  ") or "<br>" in curr_line.lower() or curr_line.endswith("\\"):
            return False
        curr_indent = len(curr_line) - len(curr_line.lstrip())
        next_indent = len(next_line) - len(next_line.lstrip())
        if next_indent >= 2 and next_indent > curr_indent:
            return False
        if stop_pattern.match(n_strip):
            return False
        if kv_pattern.match(n_strip):
            return False
        if any(c in next_line for c in ["──", "┬", "│", "└──", "├──"]):
            return False
        if re.match(r'^\s*```', next_line) or re.search(r'<table\b', next_line, re.I):
            return False
        return True

    raw_lines = cleaned_md.splitlines()
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        l_strip = line.strip()

        if not l_strip:
            flush_table()
            flush_tree()
            i += 1
            continue

        indent = len(line) - len(line.lstrip())

        # Standalone code fences (```, ```markdown, ```html)
        if re.match(r'^\s*```', l_strip):
            flush_table()
            flush_tree()
            i += 1
            continue

        # Preserved HTML Table or SVG markup
        if re.search(r'<table\b', l_strip, re.I) or l_strip.startswith(('<svg', '<div class="doc-svg-table"')):
            flush_table()
            flush_tree()
            html_block = [line]
            closing_tag = '</svg>' if '<svg' in line else ('</table>' if '<table' in line.lower() else '</div>')
            while i + 1 < len(raw_lines) and closing_tag not in html_block[-1].lower():
                i += 1
                html_block.append(raw_lines[i])
            body_blocks.append("\n".join(html_block))
            last_block_type = "table"
            i += 1
            continue

        # Markdown / Pipe Table Row (starts with | or contains multiple |)
        is_pipe_line = l_strip.startswith("|") or (
            l_strip.count("|") >= 2 and not l_strip.startswith(("#", "Article", "Chapter", "Section"))
        ) or (in_table and "|" in l_strip)
        if is_pipe_line:
            flush_tree()
            in_table = True
            table_lines.append(l_strip)
            last_block_type = "table"
            i += 1
            continue
        elif in_table:
            flush_table()

        # ASCII Tree / Organization Diagram
        if any(c in line for c in ["──", "┬", "│", "└──", "├──"]):
            flush_table()
            in_tree = True
            tree_lines.append(line)
            last_block_type = "tree"
            i += 1
            continue
        elif in_tree:
            flush_tree()

        # Existing Stamp Table Markup
        if '<table class="stamp-table"' in line:
            body_blocks.append(line)
            last_block_type = "table"
            i += 1
            continue

        # Universal Markdown Headings (# to #####)
        m_heading = re.match(r'^(#{1,6})\s*(.*)$', l_strip)
        if m_heading:
            h_hashes = m_heading.group(1)
            h_text = m_heading.group(2).strip()
            h_len = len(h_hashes)
            if h_len == 1:
                body_blocks.append(f'<div class="doc-title">{h_text}</div>')
            elif h_len == 2:
                body_blocks.append(f'<div class="doc-chapter">{h_text}</div>')
            elif h_len == 3:
                body_blocks.append(f'<div class="doc-section">{h_text}</div>')
            elif h_len == 4:
                body_blocks.append(f'<div class="doc-article-title">{h_text}</div>')
            else:
                body_blocks.append(f'<div class="doc-subheading">{h_text}</div>')
            last_block_type = "heading"
            i += 1
            continue

        # Chapter Heading without #
        m_chap = re.match(
            r'^(?:Chapter\s+\d+|CHAPTER\s+\d+|第\s*\d+\s*章|Appended\s+Table|Supplementary\s+Provisions)\b[:\s]*(.*)$',
            l_strip,
            re.I
        )
        if m_chap:
            chap_title = l_strip.strip()
            body_blocks.append(f'<div class="doc-chapter">{chap_title}</div>')
            last_block_type = "heading"
            i += 1
            continue

        # Section Heading without #
        m_sec = re.match(r'^(?:Section\s+\d+|SECTION\s+\d+|第\s*\d+\s*節)\b[:\s]*(.*)$', l_strip, re.I)
        if m_sec:
            sec_title = l_strip.strip()
            body_blocks.append(f'<div class="doc-section">{sec_title}</div>')
            last_block_type = "heading"
            i += 1
            continue

        # Article Heading without #
        m_art = re.match(r'^(?:Article\s+\d+|ARTICLE\s+\d+|第\s*\d+\s*条)\b[:\s]*(.*)$', l_strip, re.I)
        if m_art:
            art_title = l_strip.strip()
            body_blocks.append(f'<div class="doc-article-title">{art_title}</div>')
            last_block_type = "heading"
            i += 1
            continue

        # Decimal Clause (e.g. 4.1 In principle..., 8.2 ..., 10.1 ...)
        m_clause = re.match(r'^(\d+[A-Za-z]?(?:\.\d+)+)\s+(.*)$', l_strip)
        if m_clause:
            c_num = m_clause.group(1)
            c_parts = [m_clause.group(2)]
            while i + 1 < len(raw_lines) and is_continuation_line(raw_lines[i], raw_lines[i + 1]):
                c_parts.append(raw_lines[i + 1].strip())
                i += 1
            c_body = " ".join(c_parts)
            body_blocks.append(f'<div class="doc-clause"><b>{c_num}</b> {c_body}</div>')
            last_block_type = "clause"
            i += 1
            continue

        # Numbered Item with dot (e.g. 1. Pension Handbook, 2. ...)
        m_item = re.match(r'^(\d+[.)、])\s*(.+)$', l_strip)
        if m_item:
            num = m_item.group(1)
            i_parts = [m_item.group(2)]
            while i + 1 < len(raw_lines) and is_continuation_line(raw_lines[i], raw_lines[i + 1]):
                i_parts.append(raw_lines[i + 1].strip())
                i += 1
            item_body = " ".join(i_parts)
            body_blocks.append(f'<div class="doc-item"><b>{num}</b> {item_body}</div>')
            last_block_type = "item"
            i += 1
            continue

        # Bullet Item (•, -, *, ▪, ▫, ○, ·)
        m_bullet = re.match(r'^(?:[•\*\-▪▫○·])\s+(.*)$', l_strip)
        if m_bullet:
            b_parts = [m_bullet.group(1)]
            while i + 1 < len(raw_lines) and is_continuation_line(raw_lines[i], raw_lines[i + 1]):
                b_parts.append(raw_lines[i + 1].strip())
                i += 1
            b_body = " ".join(b_parts)
            # Indent subordinate bullets: if indented or following a subitem / sub-bullet
            is_sub = (indent >= 2) or (last_block_type in ("subitem", "sub_bullet", "subitem_desc"))
            if is_sub:
                body_blocks.append(f'<div class="doc-sub-bullet">• {b_body}</div>')
                last_block_type = "sub_bullet"
            else:
                body_blocks.append(f'<div class="doc-bullet-item">• {b_body}</div>')
                last_block_type = "bullet"
            i += 1
            continue

        # Subitem with circled or parenthesized number (e.g. ① Regular Employee, (1) Condition)
        m_sub = re.match(r'^([①-⑳]|\(\d+\))\s*(.*)$', l_strip)
        if m_sub:
            s_mark = m_sub.group(1)
            s_parts = [m_sub.group(2)]
            while i + 1 < len(raw_lines) and is_continuation_line(raw_lines[i], raw_lines[i + 1]):
                s_parts.append(raw_lines[i + 1].strip())
                i += 1
            s_body = " ".join(s_parts)
            body_blocks.append(f'<div class="doc-subitem"><b>{s_mark}</b> {s_body}</div>')
            last_block_type = "subitem"
            i += 1
            continue

        # Item Title or Clause starting with unpunctuated number (e.g. "1 Injury..." or "5 When it is suspected...")
        m_num_item = re.match(r'^(\d+)\s+(\S.*)$', l_strip)
        if m_num_item:
            u_num = m_num_item.group(1)
            rest_text = m_num_item.group(2).strip()
            i_parts = [rest_text]
            while i + 1 < len(raw_lines) and is_continuation_line(raw_lines[i], raw_lines[i + 1]):
                i_parts.append(raw_lines[i + 1].strip())
                i += 1
            item_body = " ".join(i_parts)
            body_blocks.append(f'<div class="doc-item"><b>{u_num}.</b> {item_body}</div>')
            last_block_type = "item"
            i += 1
            continue

        # Unnumbered indented line or definition/key-value line under bullet/item
        if (indent >= 2 or last_block_type in ("bullet", "sub_bullet", "subitem", "subitem_desc")) and kv_pattern.match(l_strip):
            body_blocks.append(f'<div class="doc-subitem-desc">{l_strip}</div>')
            last_block_type = "subitem_desc"
            i += 1
            continue

        # Unnumbered indented line under bullet or item
        if indent >= 2:
            body_blocks.append(f'<div class="doc-subitem-desc">{l_strip}</div>')
            last_block_type = "subitem_desc"
            i += 1
            continue

        # Standard Paragraph (joining continuation lines)
        p_parts = [l_strip]
        while i + 1 < len(raw_lines) and is_continuation_line(raw_lines[i], raw_lines[i + 1]):
            p_parts.append(raw_lines[i + 1].strip())
            i += 1
        p_text = " ".join(p_parts)
        body_blocks.append(f'<div class="doc-paragraph">{p_text}</div>')
        last_block_type = "paragraph"
        i += 1

    flush_table()
    flush_tree()

    footer_html = f'<div class="page-footer">{page_num}</div>' if page_num is not None else ""
    full_body = "\n".join(body_blocks) + footer_html
    # Preserve explicit rowspan/colspan and cell associations from the source.
    return f"<!DOCTYPE html><html><head><style>{css}</style></head><body>{full_body}</body></html>"
