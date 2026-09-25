"""
===============================================================================
Document Rules and Prompts Subpackage
===============================================================================

Purpose:
    Exposes document layout rules, translation prompt templates, and
    language-pair specific grammar guidelines:
      - document_rules : Universal structural rules and combined rule generator
      - prompt_templates : Language pair prompt definitions and tone configurations
===============================================================================
"""

from __future__ import annotations

from backend.rules.document_rules import GENERAL_DOCUMENT_RULES, get_combined_rules
from backend.rules.prompt_templates import TRANSLATION_RULES, get_rules

__all__: list[str] = [
    "GENERAL_DOCUMENT_RULES",
    "get_combined_rules",
    "TRANSLATION_RULES",
    "get_rules",
]
