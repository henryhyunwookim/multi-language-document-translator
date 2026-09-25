"""
===============================================================================
Abstract Base Document Handler Interface Module
===============================================================================

Purpose:
    Defines the architectural contract and shared lifecycle methods for all
    format-specific document handlers (e.g. Scanned PDF, Digital PDF, Word,
    PowerPoint, Excel, Image, Markdown, Plain Text).

Usage:
    class MyCustomHandler(BaseDocumentHandler):
        def process(self, input_file: Any, **kwargs) -> io.BytesIO:
            ...

===============================================================================
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from typing import Any, BinaryIO, Optional, Union


# =============================================================================
# ABSTRACT BASE HANDLER
# =============================================================================

class BaseDocumentHandler(ABC):
    """
    Abstract contract for document processors.

    Attributes:
        translator (Any): Reference to the parent translator orchestrator instance.
    """

    def __init__(self, translator: Any) -> None:
        """
        Initializes the handler with a reference to the orchestrating translator.

        Args:
            translator (Any): Orchestrator instance providing logging, model inference,
                              and cancellation polling hooks.
        """
        self.translator = translator

    @abstractmethod
    def process(self, input_file: Union[BinaryIO, bytes, io.BytesIO, Any], **kwargs: Any) -> io.BytesIO:
        """
        Processes the input document and returns the translated artifact as a BytesIO stream.

        Args:
            input_file (Union[BinaryIO, bytes, io.BytesIO, Any]): File-like object or binary buffer.
            **kwargs: Additional handler-specific format or layout options.

        Returns:
            io.BytesIO: Positioned (seek 0) byte stream containing translated output document.

        Raises:
            NotImplementedError: Subclasses must provide format-specific execution logic.
        """
        raise NotImplementedError("Document handlers must implement the process() method.")

    def check_cancelled(self) -> None:
        """
        Polls the parent translator to verify whether the operation was cancelled by user.
        Raises an exception or halts processing if cancellation is triggered.
        """
        if hasattr(self.translator, "check_cancelled"):
            self.translator.check_cancelled()

    def log(
        self,
        message: str,
        stage: Optional[str] = None,
        progress: Optional[int] = None,
    ) -> None:
        """
        Dispatches structured progress and diagnostic logs to parent translator.

        Args:
            message (str): Human-readable progress description.
            stage (Optional[str]): Pipeline phase identifier (e.g. 'INIT', 'EXTRACT', 'TRANSLATE', 'RENDER').
            progress (Optional[int]): Estimated percent completion (0 - 100).
        """
        if hasattr(self.translator, "log"):
            self.translator.log(message, stage=stage, progress=progress)
