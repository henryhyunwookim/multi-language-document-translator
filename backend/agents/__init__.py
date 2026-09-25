"""
Multi-Agent Document Translation Package.
Decomposes document processing into collaborative vision, translation, table,
and reflection critic agents coordinated via LangGraph and traced in LangSmith.
"""

from backend.agents.state import DocumentPageState
from backend.agents.graph import create_document_agent_graph, run_page_agent_pipeline

__all__ = [
    "DocumentPageState",
    "create_document_agent_graph",
    "run_page_agent_pipeline",
]
