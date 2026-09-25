"""
State definition for LangGraph Multi-Agent Document Translation.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict


class DocumentPageState(TypedDict, total=False):
    """
    Shared state passed between multi-agent pipeline nodes for a single document page.
    """
    page_idx: int
    image_ref: str
    image_bytes: Optional[bytes]
    width: float
    height: float
    target_lang: str
    source_lang: str
    model_name: str
    api_key: str
    page_type: str  # 'toc' | 'table_dense' | 'structured_clauses' | 'standard'
    layout_meta: dict[str, Any]
    draft_markdown: str
    
    # Gate 1: Translation Semantic Critic State
    translation_critique: str
    translation_iteration: int
    translation_passed: bool
    max_translation_retries: int  # Default: 2 retries (up to 3 passes total)

    # Gate 2: Structural & Layout Linter Critic State
    format_critique: str
    format_iteration: int
    format_passed: bool
    max_format_retries: int  # Default: 2 retries (up to 3 passes total)

    # Backward compatibility fields
    critique: str
    iteration: int
    review_passed: bool

    final_html: str
    quality_status: str
    error: Optional[str]
