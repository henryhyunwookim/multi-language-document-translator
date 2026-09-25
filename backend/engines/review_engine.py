"""
===============================================================================
Universal Document Review and Audit Engine Module
===============================================================================

Purpose:
    Performs sliding-window multi-page quality auditing to identify and repair:
      - Numbering continuity resets across page boundaries (e.g. Page A ends at
        item 6, Page B inadvertently restarts numbering at 1 instead of 7)
      - Severed cross-references (e.g. "Items 7 through 10" mismatching definitions)
      - Collapsed clauses and lines merged into single running paragraphs
      - Artificial bullet markers prepended to pre-numbered items
      - Promoted sub-bullets and page boundary artifacts

Algorithmic Design:
    Uses a sliding-window strategy with window_size = 6 and step_size = 4, providing
    a 2-page overlap between adjacent windows. This guarantees that any boundary
    discontinuity between page N and page N+1 falls squarely within at least one
    reviewer inspection window. Executes bounded review iterations (default max: 2).

Usage:
    from backend.engines.review_engine import DocumentReviewEngine

    reviewer = DocumentReviewEngine(model=gemini_model, target_lang="English")
    audited_pages = reviewer.review_pages(translated_pages, max_review_loops=2)

===============================================================================
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

from backend.core.observability import traceable_step

try:
    from backend.core.logger_config import setup_logging
except ImportError:
    try:
        from backend.logger_config import setup_logging
    except ImportError:
        try:
            from logger_config import setup_logging
        except ImportError:
            setup_logging = lambda name: logging.getLogger(name)

logger = setup_logging("document_review")


# =============================================================================
# DOCUMENT REVIEW & QUALITY AUDIT ENGINE CLASS
# =============================================================================

class DocumentReviewEngine:
    """
    Quality inspection engine utilizing Gemini to audit and repair translated Markdown pages.
    """

    def __init__(
        self,
        model: Any,
        target_lang: str = "English",
        log_callback: Optional[Callable[..., Any]] = None,
        check_cancelled: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Initializes the review engine.

        Args:
            model (Any): Generative AI model instance supporting generate_content.
            target_lang (str): Target translation language (e.g. 'English', 'Japanese').
            log_callback (Optional[Callable]): Logging callback for UI/orchestrator events.
            check_cancelled (Optional[Callable]): Polling hook to detect user cancellation.
        """
        self.model = model
        self.target_lang = target_lang
        self.log_callback = log_callback
        self.check_cancelled = check_cancelled or (lambda: None)

    def _log(self, msg: str, stage: str = "REVIEW", progress: Optional[int] = None) -> None:
        """Dispatches internal log events to standard logger and UI callback."""
        logger.info(msg)
        if self.log_callback:
            try:
                self.log_callback(msg, stage=stage, progress=progress)
            except TypeError:
                self.log_callback(msg)

    # -------------------------------------------------------------------------
    # Review Loop & Sliding-Window Orchestration
    # -------------------------------------------------------------------------

    @traceable_step(name="document_review_engine", run_type="chain")
    def review_pages(self, translated_pages: dict[int, str], max_review_loops: int = 2) -> dict[int, str]:
        """
        Audits multi-page translated Markdown content in a bounded loop (up to max_review_loops).

        Identifies and repairs numbering continuity errors, severed cross-references,
        collapsed lines/paragraphs, promoted sub-bullets, and page-boundary artifacts.

        Args:
            translated_pages (dict[int, str]): Mapping of 0-indexed page number to Markdown text.
            max_review_loops (int): Maximum iterative audit cycles before terminating.

        Returns:
            dict[int, str]: Verified and repaired mapping of page indices to Markdown text.
        """
        if not translated_pages:
            return translated_pages

        sorted_page_keys = sorted(translated_pages.keys())
        total_pages = len(sorted_page_keys)
        self._log(
            f"Starting universal document quality & numbering review for {total_pages} pages (max loops: {max_review_loops})...",
            stage="REVIEW",
            progress=70,
        )

        # Sliding window parameters: Window size 6, Step size 4 -> 2 pages overlap
        window_size = 6
        step_size = 4

        for loop_idx in range(max_review_loops):
            self.check_cancelled()
            loop_num = loop_idx + 1
            loop_progress = 70 + int(loop_idx * 8)
            self._log(f"--- Review Loop {loop_num}/{max_review_loops} ---", stage="REVIEW", progress=loop_progress)
            total_issues_fixed_in_loop = 0

            # Partition pages into overlapping review windows
            windows: list[tuple[int, list[int]]] = []
            for win_start in range(0, total_pages, step_size):
                win_keys = sorted_page_keys[win_start:min(win_start + window_size, total_pages)]
                windows.append((win_start, win_keys))

            # -----------------------------------------------------------------
            # Window Prompt Formulation & JSON Extraction
            # -----------------------------------------------------------------
            def review_single_window(
                w_idx: int,
                w_start: int,
                w_keys: list[int],
            ) -> tuple[int, int, int, dict[str, Any], list[str]]:
                self.check_cancelled()
                local_logs: list[str] = []
                window_content: list[str] = []
                for p_idx in w_keys:
                    text = translated_pages.get(p_idx, "")
                    window_content.append(f"=== PAGE {p_idx + 1} ===\n{text}")

                review_input = "\n\n".join(window_content)
                first_page_num = w_keys[0] + 1
                last_page_num = w_keys[-1] + 1

                review_prompt = f"""You are a Lead Document Quality & Structural Integrity Reviewer.
Inspect the following consecutive translated document pages ({first_page_num} to {last_page_num}) for numbering, line integrity, structural, and cross-reference errors.

TARGET LANGUAGE: {self.target_lang}

REVIEW CRITERIA:
1. Numbering continuity across page transitions:
   - Carefully inspect how sections, clauses, and lists continue across pages.
   - If a section, clause, or list on Page N ends at item N, and Page N+1 continues the SAME sequence with items restarting at 1, 2, 3..., that is an ERROR caused by a page-boundary reset!
   - You MUST restore continuous numbering on Page N+1 (e.g., if Page N ends at item 6, renumber 1, 2, 3... on Page N+1 to 7, 8, 9... to maintain consecutive sequence).
2. Cross-page table continuity:
   - Explicitly audit tables spanning page boundaries: when Page N ends with a table (or unclosed table rows), inspect Page N+1 to ensure continuation rows remain in proper table format (standard HTML `<table>` or Markdown table) with consistent column structures, rather than devolving into malformed paragraphs or raw pipe strings.
3. Line break & item integrity:
   - Verify that separate numbered items, clauses, or headings (e.g., 4.1, 4.2, 4.3 or 8.1, 8.2) are NOT collapsed into a single inline paragraph. Keep every item on its own line.
   - Ensure list items in Table of Contents, subordinate key-value tiers (such as length-of-service conditions or duration tiers), or itemized requirements each occupy their own line and are NEVER collapsed into running prose.
4. No arbitrary bullets:
   - Remove any artificial bullet markers (• or -) prepended directly before numbered item labels (e.g. change "• 8.1" to "8.1", "• ①" to "①", "• (1)" to "(1)").
   - Do NOT remove or strip bullets from subordinate list items or nested sub-points (e.g. preserve subordinate bulleted lines indented under a parent item).
5. Markdown & formatting hygiene:
   - Remove stray code block backticks (``` or ```markdown) and raw heading hashes (# markers) in prose or TOC lines (e.g. "### Section" embedded in running text or TOC entries).
6. Cross-reference integrity:
   - Check references like "Items 7 through 10", "items 1 through 4 above", "Items 1 through 3, and Item 5".
   - The numbered items defined in the text MUST match what the subsequent clauses reference.
7. Hierarchy & Sub-bullets:
   - Ensure sub-items, bullet points under parent items, and condition definitions remain indented sub-items and are NOT promoted to top-level numbers or outdented to margin.
8. Page boundary artifacts:
   - Remove orphaned dangling words or sentence fragments at the top or bottom of a page.
9. Source fidelity:
   - Do not invent, infer, normalize, or alter dates, times, quantities, ranges, section numbers, or table values.
   - Never remove trailing numbered items. If the supplied page text visibly contains continuous items in sequence, restore every item in order without omission.
   - Never rotate, transpose, or repeat table content. Preserve each row and merged-cell value once.
10. Table of Contents preservation:
   - For Table of Contents pages (listing chapters, sections, or articles with page numbers):
   - Maintain strict line discipline: every chapter, section, and article MUST remain on its own line; never collapse them into running prose.
   - Preserve hierarchical indentation across page boundaries (e.g., articles under a section must remain indented).
   - Do NOT append standalone bottom-of-page numbers (e.g. '1', '2') to the last TOC entry.
   - Do NOT add invented page numbers to entries that lack page numbers in the source.

If there are NO numbering, line integrity, or boundary errors across these pages, return:
{{"has_issues": false, "issues": [], "corrected_pages": {{}}}}

If there ARE errors, return a JSON object with:
{{
  "has_issues": true,
  "issues": ["Clear description of issue 1", "Clear description of issue 2"],
  "corrected_pages": {{
    "<page_number>": "<full corrected markdown text for that specific page with exact corrected numbers, linebreaks, and formatting>"
  }}
}}

PAGES TO REVIEW:
{review_input}
"""
                try:
                    self.check_cancelled()
                    resp = self.model.generate_content(
                        review_prompt,
                        generation_config={"response_mime_type": "application/json"},
                        request_options={"timeout": 120},
                    )
                    if resp and resp.text:
                        raw_json = resp.text.strip()
                        if raw_json.startswith("```json"):
                            raw_json = raw_json[7:]
                        if raw_json.startswith("```"):
                            raw_json = raw_json[3:]
                        if raw_json.endswith("```"):
                            raw_json = raw_json[:-3]

                        data = json.loads(raw_json.strip())
                        return w_idx, first_page_num, last_page_num, data, local_logs
                except Exception as exc:
                    local_logs.append(
                        f"Notice: Review check for pages {first_page_num}-{last_page_num} encountered: {exc}. "
                        f"Keeping existing translation."
                    )
                return w_idx, first_page_num, last_page_num, {"has_issues": False}, local_logs

            # -----------------------------------------------------------------
            # Page Correction Application & Sequenced State Reconciliation
            # -----------------------------------------------------------------
            review_workers = min(3, len(windows)) if windows else 1
            completed_windows: dict[int, tuple[int, int, dict[str, Any], list[str]]] = {}
            next_expected_win = 0

            with ThreadPoolExecutor(max_workers=review_workers) as executor:
                futures = [executor.submit(review_single_window, i, ws, wk) for i, (ws, wk) in enumerate(windows)]
                for f in as_completed(futures):
                    self.check_cancelled()
                    w_idx, p_start, p_end, data, w_logs = f.result()
                    completed_windows[w_idx] = (p_start, p_end, data, w_logs)

                    # Monotonically process and log completed windows in logical page sequence (0, 1, 2...)
                    while next_expected_win in completed_windows:
                        win_start, win_end, win_data, win_logs = completed_windows.pop(next_expected_win)
                        for log_msg in win_logs:
                            self._log(log_msg, stage="REVIEW")

                        if win_data.get("has_issues"):
                            issues = win_data.get("issues", [])
                            corrected = win_data.get("corrected_pages", {})
                            for p_num_str, corr_text in corrected.items():
                                try:
                                    p_num = int(p_num_str)
                                    target_key: Optional[int] = None
                                    for k in sorted_page_keys:
                                        if (k + 1) == p_num or k == p_num:
                                            target_key = k
                                            break
                                    if target_key is not None and corr_text.strip():
                                        translated_pages[target_key] = corr_text.strip()
                                        total_issues_fixed_in_loop += 1
                                except ValueError:
                                    continue
                            if issues:
                                self._log(
                                    f"Review Loop {loop_num} (Pages {win_start}-{win_end}): Fixed: {'; '.join(issues)}",
                                    stage="REVIEW",
                                )
                        next_expected_win += 1

            if total_issues_fixed_in_loop == 0:
                self._log(
                    f"Review Loop {loop_num}: Verification passed. Document structure and numbering are consistent.",
                    stage="REVIEW",
                    progress=86,
                )
                break
            else:
                self._log(
                    f"Review Loop {loop_num}: Applied {total_issues_fixed_in_loop} page corrections.",
                    stage="REVIEW",
                    progress=84,
                )

        return translated_pages
