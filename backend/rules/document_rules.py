"""
===============================================================================
Universal Document Structure, Layout, and Formatting Rules Module
===============================================================================

Purpose:
    Defines universal, document-agnostic, and language-independent formatting
    rules for all complex documents (reports, manuals, contracts, regulations,
    technical documentation, academic papers, books, and business forms).
    Combines universal structural rules (headings, clauses, tables, stamps) with
    language-pair specific grammar and tone guidelines.

Usage:
    from backend.rules.document_rules import GENERAL_DOCUMENT_RULES, get_combined_rules

    rules = get_combined_rules(source_lang="Japanese", target_lang="English")

===============================================================================
"""

from __future__ import annotations

# =============================================================================
# UNIVERSAL DOCUMENT RULES DEFINITION
# =============================================================================

GENERAL_DOCUMENT_RULES: str = """
UNIVERSAL DOCUMENT STRUCTURE & LAYOUT RULES:

1. HEADINGS & HIERARCHY STRUCTURE:
   - Use standard Markdown headings to preserve clear visual hierarchy:
     * `# Document Title / Major Division` for top-level titles or parts.
     * `## Major Section / Chapter` for chapters, main divisions, schedules, or appended sections.
     * `### Subsection / Topic` for sections, subsections, or sub-chapters.
     * `#### Article / Item / Subheading` for individual articles, items, or titled clauses (e.g. `#### Section 1 (Scope)` or `#### Article 1 (Purpose)`).
   - ALWAYS leave a blank line before and after each heading.

2. LINE BREAK & PARAGRAPH FIDELITY:
   - Every distinct clause, sub-clause, numbered item, bullet point, subordinate condition/tier (such as length-of-service tiers or duration lists), table row, or heading in the source document MUST remain on its own line.
   - NEVER collapse or merge separate lines, tiers, or conditions into running prose or inline paragraphs (e.g., keep items 4.1, 4.2, 4.3 on separate lines; do NOT merge length-of-service conditions or duration lists into one continuous block).
   - Use double line breaks between distinct articles, sections, or distinct body paragraphs.

3. LIST & BULLET DISCIPLINE (NO ARBITRARY BULLETS OR NUMBERING):
   - NEVER add arbitrary bullet symbols (•, -, *) to lines that do not have them in the original.
   - NEVER prepend bullet markers to items that are already numbered or marked:
     * If source has "8.1 Topic Heading", write "8.1 Topic Heading" (NOT "- 8.1 Topic Heading").
     * If source has "① Primary Category", write "① Primary Category" (NOT "- ① Primary Category" or "1. Primary Category").
     * If source has "(1) Condition A", write "(1) Condition A" (NOT "• (1) Condition A" or "1. Condition A").
     * If source has unpunctuated number like "1 Supporting Material", write "1 Supporting Material" (NOT "• 1 Supporting Material" or "(1) Supporting Material").
   - PRESERVE GENUINE NESTED BULLETS: If an item or clause contains indented bullet points (e.g., indented sub-items or revision lists), you MUST preserve them as indented bullets (`- ` or `• `). Do NOT strip bullets from items merely because the text references a numbered item or section.
   - Strictly preserve the original labeling style:
     * If the source uses circled numbers (①, ②, ③), output circled numbers (①, ②, ③).
     * If the source uses parenthesized numbers ((1), (2)), output parenthesized numbers ((1), (2)).
     * If the source uses native/symbolic numerals (e.g., Roman I, II, III or CJK 一, 二, 三), translate or preserve them faithfully while maintaining the itemized structure.
     * If the source uses unnumbered indented lines or dashes, keep them as unadorned indented lines.
     * Do NOT convert circled or parenthesized items into numbered lists or invent parentheses.
   - CONTINUOUS NUMBERING: Do NOT restart numbering at 1 if a list, section, or sequence continues from an earlier page or starts with a specific number (e.g., 30., 31., 32. or 7., 8., 9.). NEVER renumber continuous sequences to 1, 2, 3.

4. TABLE OF CONTENTS:
   - Every chapter, section, and entry must be on its own distinct line.
   - Format entries with page numbers as: `[Entry Title] ··· [Page]` or `[Entry Title] [Page]`.
   - Preserve hierarchical indentation using leading spaces or sub-level depth (e.g., Chapters at 0 indent, Sections indented 2-4 spaces, Articles indented under Sections 4-8 spaces).
   - If an entry has no page number in the original source, output `[Entry Title]` on its own line without adding arbitrary or invented page numbers.
   - Do NOT format Table of Contents entries as Markdown tables or pipe tables (`| ... |`). Use standard lines.
   - Do NOT include leading markdown hashes (`###`) in TOC lines.
   - Footer page numbers: If a page number appears alone at the bottom of the page, output it as `[Page: N]` on the final line, never merged with the last TOC entry.

5. TABLES, SCHEDULES & MULTI-COLUMN DATA:
   - CRITICAL REQUIREMENT FOR TABLES: Whenever text in the source document appears in a table, schedule, column layout, or structured grid, you MUST format it as a clean Markdown table with pipes (`| Col 1 | Col 2 | ...`) or a standard HTML `<table>`.
   - MULTI-TIER COMPLEX HEADERS:
     * For tables with grouped headers spanning sub-columns, format columns with distinct matching headers.
     * WIDE TABLES & COMPACT SUB-COLUMNS: In tables with many columns (e.g. 6+ columns, monthly ranges, date schedules), keep sub-column headers concise (`4/1 ~ 4/30`, `5/1 ~ 5/31`, etc.) and place the overarching category in the top-left header cell (e.g. `Years of Service / Month of Joining`) or overarching `<th colspan="N">` tier. NEVER bloat individual sub-column cells by redundantly repeating long parent category phrases across every column.
   - VERTICAL CATEGORY ROWSPAN: When a table features vertically merged labels or categories across multiple sub-rows, keep empty cells in subsequent rows without shifting columns leftward.
   - COLUMN POSITIONAL INVARIANCE & EMPTY CELLS: Every column represents a distinct semantic field (e.g. Item | Condition | Field A | Field B).
     * Missing leading cells: If a row represents a sub-item under an existing parent without its own sequence number, you MUST start the row with an empty cell (`| | Sub-item | ... |` or `<td></td><td>Sub-item</td>...`). Never omit the leading empty cell!
     * Missing middle cells: If a row lacks a value for a middle column, that middle cell MUST remain explicitly empty (`<td></td>` or `| |`). Values from subsequent columns MUST NEVER shift into an empty middle column!
   - EMPTY CELLS & EXACT COLUMN COUNTS: Every single row in a table MUST have the exact same number of columns as the header. Never omit trailing or empty cells. In Markdown tables, explicitly output `| |` for empty cells.
   - MERGED ROWS & CELLS: When a table has a cell that spans across multiple columns (such as a shared value, category label, summary row, or explanatory note applying across multiple columns), format it as a single merged cell using standard HTML `colspan` (e.g., `<td colspan="N">[Value]</td>`) or standard table format. NEVER repeat the same value across every individual column cell when it visually forms a single merged cell in the source document.
   - BORDERLESS TWO-COLUMN LISTS & KEY-VALUE GRIDS: When itemized lists (bullets `•`, numbered lists, or key-value entries) are visually arranged in two aligned columns across the page without visible borders (e.g., left column: key or event; right column: value, deadline, or detail), this is a 2-column key-value table. You MUST preserve this two-column alignment using a clean HTML table (`<table class="borderless"><tr><td style="border: none; width: 55%; vertical-align: top;">• [Item]</td><td style="border: none; width: 45%; vertical-align: top;">[Detail]</td></tr></table>`) or a 2-column pipe table. NEVER collapse side-by-side two-column bullet pairs into a single running line (e.g., do NOT turn it into `• Item: Detail`).
   - CROSS-PAGE SPLIT TABLES: If a table splits across pages, continue the table on the next page in proper table format (`<table>` or Markdown table) with consistent column structures. Do NOT devolve table rows into unstructured text.
   - SIMPLE 2D TABLES: Simple flat tables without cell merging may use standard Markdown tables (`| ... |`) with header delimiters (`|---|---|`), ensuring every row contains all column pipes.
   - NEVER output table data as flattened, unformatted running text lines.
   - For organization diagrams or hierarchy branches using box-drawing characters (──┬──, └──), preserve the ASCII diagram structure cleanly.

6. MATHEMATICAL FORMULAS & FRACTIONS:
   - NEVER output raw LaTeX math syntax (such as `$$...$$`, `\\frac{...}{...}`, or `\\text{...}`) because PDF rendering engines do not process LaTeX.
   - Format mathematical formulas and division calculations as:
     (a) Clear text division notation: `[Variable] = ([Numerator]) / ([Denominator])`, OR
     (b) A clean 2-row division fraction table without rowspan:
         `<table class="formula-table" style="margin: 8pt auto; border-collapse: collapse; border: none;"><tr><td style="border: none; vertical-align: bottom; text-align: right; padding: 2pt 8pt 2pt 0; font-weight: 600; font-size: 8.5pt; white-space: nowrap;">[Variable] =</td><td style="border: none; border-bottom: 1.5pt solid #0f172a; padding: 2pt 8pt; font-size: 8pt; text-align: center; vertical-align: bottom;">[Numerator]</td></tr><tr><td style="border: none; padding: 0;"></td><td style="border: none; padding: 2pt 8pt; font-size: 8pt; text-align: center; vertical-align: top;">[Denominator]</td></tr></table>`

7. OFFICIAL SEALS, STAMPS & COVER PAGES:
   - Official seals, approval markings, or verification stamps (e.g., stamps, watermarks, organizational seals) must be formatted as:
     [Stamp: Organization / Details / Date]
   - Title / Cover Pages: Present the main title clearly centered with generous spacing, with dates and approval marks appropriately positioned.
   - Page Numbers: If a page number appears in the source footer, place it on its own line at the end: [Page: N].
"""


# =============================================================================
# RULE COMBINATION & LOCALIZATION API
# =============================================================================

def get_combined_rules(source_lang: str = "", target_lang: str = "English") -> str:
    """
    Combines universal document formatting rules with language-pair specific linguistic rules.

    Ensures all document translations adhere strictly to layout and hierarchy fidelity
    regardless of source/target language pair or document type, without hardcoding or language bias.

    Args:
        source_lang (str): Source language (e.g. "Japanese", "French", "English"). Optional.
        target_lang (str): Target translation language (e.g. "English", "Spanish", "Japanese").

    Returns:
        str: Consolidated rule string ready for injection into AI prompts.
    """
    try:
        from backend.rules.prompt_templates import get_rules
    except ImportError:
        try:
            from .prompt_templates import get_rules
        except ImportError:
            try:
                from backend.prompt_templates import get_rules
            except ImportError:
                from prompt_templates import get_rules

    linguistic_rules = get_rules(source_lang=source_lang, target_lang=target_lang)

    if linguistic_rules:
        target_display = target_lang.upper() if target_lang else "TARGET LANGUAGE"
        return f"{GENERAL_DOCUMENT_RULES}\n\nLINGUISTIC & GRAMMAR RULES FOR {target_display}:\n{linguistic_rules}"
    return GENERAL_DOCUMENT_RULES
