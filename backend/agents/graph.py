"""
LangGraph Assembly for Multi-Agent Document Translation.
Orchestrates page classification, translation, structural table parsing,
reflection critique, and typesetting into an executable state machine.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.nodes import (
    classifier_node,
    clear_page_image,
    formatting_critic_node,
    store_page_image,
    store_page_model,
    table_specialist_node,
    translation_critic_node,
    translator_node,
    typesetter_node,
)
from backend.agents.state import DocumentPageState
from backend.core.observability import init_langsmith, traceable_step

logger = logging.getLogger(__name__)

# Cached compiled graph instance
_COMPILED_GRAPH: Any = None


def create_document_agent_graph():
    """
    Constructs and compiles the staged multi-agent workflow graph:
    1. Classifier Agent -> identifies structural layout & metadata
    2. Translation Agent -> translates content accurately
    3. Micro-Gate 1: Translation Semantic Critic -> verifies omissions, entities, register
    4. Table & Structure Specialist Agent -> repairs formulas, TOC, tables, and squashed lines
    5. Micro-Gate 2: Structural & Layout Linter Critic -> validates line discipline, tables, and HTML renderability
    6. Typesetter Agent -> converts audited markdown into publication-ready HTML
    """
    workflow = StateGraph(DocumentPageState)

    # 1. Register specialized agent nodes
    workflow.add_node("classifier", classifier_node)
    workflow.add_node("translator", translator_node)
    workflow.add_node("translation_critic", translation_critic_node)
    workflow.add_node("table_specialist", table_specialist_node)
    workflow.add_node("formatting_critic", formatting_critic_node)
    workflow.add_node("typesetter", typesetter_node)

    # 2. Wire baseline progression edges
    workflow.add_edge(START, "classifier")
    workflow.add_edge("classifier", "translator")
    workflow.add_edge("translator", "translation_critic")

    # 3. Micro-Gate 1: Translation Semantic Reflection Gate
    def route_after_translation_critic(state: DocumentPageState) -> str:
        passed = state.get("translation_passed", True)
        t_iter = state.get("translation_iteration", 1)
        max_retries = state.get("max_translation_retries", 2)
        if not passed and t_iter <= max_retries:
            logger.info(
                f"Page {state.get('page_idx', 0) + 1} failed translation critic (Attempt {t_iter}/{max_retries + 1}). "
                "Routing back to translator for semantic refinement."
            )
            return "translator"
        return "table_specialist"

    workflow.add_conditional_edges(
        "translation_critic",
        route_after_translation_critic,
        {
            "translator": "translator",
            "table_specialist": "table_specialist",
        },
    )

    workflow.add_edge("table_specialist", "formatting_critic")

    # 4. Micro-Gate 2: Structural & Layout Linter Reflection Gate
    def route_after_formatting_critic(state: DocumentPageState) -> str:
        passed = state.get("format_passed", True)
        f_iter = state.get("format_iteration", 1)
        max_retries = state.get("max_format_retries", 2)
        if not passed and f_iter <= max_retries:
            logger.info(
                f"Page {state.get('page_idx', 0) + 1} failed formatting critic (Attempt {f_iter}/{max_retries + 1}). "
                "Routing back to table & structure specialist for targeted repair."
            )
            return "table_specialist"
        return "typesetter"

    workflow.add_conditional_edges(
        "formatting_critic",
        route_after_formatting_critic,
        {
            "table_specialist": "table_specialist",
            "typesetter": "typesetter",
        },
    )

    workflow.add_edge("typesetter", END)

    return workflow.compile()


def get_agent_graph():
    """Retrieves or lazily instantiates the compiled graph."""
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = create_document_agent_graph()
    return _COMPILED_GRAPH


@traceable_step(name="page_multi_agent_pipeline", run_type="chain")
def run_page_agent_pipeline(
    page_idx: int,
    image_bytes: bytes,
    width: float,
    height: float,
    api_key: str,
    target_lang: str = "English",
    model_name: str = "gemini-3.8-flash",
    max_translation_retries: int = 2,
    max_format_retries: int = 2,
    model: Any = None,
) -> DocumentPageState:
    """
    Executes the staged multi-agent graph with localized micro-gates for a single document page.
    Automatically captures telemetry and LangSmith spans without leaking heavy image payloads.
    """
    init_langsmith()

    image_ref = f"doc_page_{page_idx}_{id(image_bytes)}"
    store_page_image(image_ref, image_bytes)
    if model is not None:
        store_page_model(image_ref, model)

    initial_state: DocumentPageState = {
        "page_idx": page_idx,
        "image_ref": image_ref,
        "image_bytes": None,  # Decoupled to keep LangSmith traces lightweight (<1 KB)
        "width": width,
        "height": height,
        "target_lang": target_lang,
        "model_name": model_name,
        "api_key": api_key,
        "page_type": "standard",
        "layout_meta": {},
        "draft_markdown": "",
        "translation_critique": "",
        "translation_iteration": 0,
        "translation_passed": True,
        "max_translation_retries": max_translation_retries,
        "format_critique": "",
        "format_iteration": 0,
        "format_passed": True,
        "max_format_retries": max_format_retries,
        "critique": "",
        "iteration": 0,
        "review_passed": True,
        "final_html": "",
        "error": None,
    }

    graph = get_agent_graph()
    try:
        final_state = graph.invoke(initial_state)
        final_state["quality_status"] = "passed" if (
            final_state.get("translation_passed", False) and final_state.get("format_passed", False)
        ) else "needs_review"
        return final_state
    finally:
        clear_page_image(image_ref)
