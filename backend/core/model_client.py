"""
Bind a generation client to one credential, never process-global defaults.

Wraps the new google-genai SDK (google.genai) behind a thin adapter that
preserves the old google.generativeai GenerativeModel.generate_content()
call signature so that no callers across the codebase need to change.
"""
from __future__ import annotations

from typing import Any, Optional

from google import genai
from google.genai import types as genai_types


class GeminiModel:
    """
    Adapter that exposes a generate_content() method matching the old
    google.generativeai.GenerativeModel interface, backed by the new
    google-genai SDK client.

    Supports:
    - Text-only prompts (str)
    - Multimodal prompts (list of str / dict with mime_type+data)
    - generation_config= dict (response_mime_type, response_schema, etc.)
    - request_options= dict with 'timeout' key
    """

    def __init__(self, model_name: str, client: genai.Client) -> None:
        self._model_name = model_name
        self._client = client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_contents(self, prompt: Any) -> list:
        """
        Convert the old-style prompt argument into the new SDK contents list.

        Old SDK accepted:
          - str → single text part
          - list of (str | dict{"mime_type":..., "data":...}) → mixed parts
        """
        if isinstance(prompt, str):
            return [prompt]
        if isinstance(prompt, list):
            parts = []
            for item in prompt:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "mime_type" in item and "data" in item:
                    # Vision / binary part
                    parts.append(
                        genai_types.Part.from_bytes(
                            data=item["data"],
                            mime_type=item["mime_type"],
                        )
                    )
                else:
                    parts.append(item)
            return parts
        # Fallback: pass through as-is
        return [prompt]

    def _build_config(
        self,
        generation_config: Optional[dict] = None,
    ) -> Optional[genai_types.GenerateContentConfig]:
        """Convert the old generation_config dict to the new SDK config object."""
        if not generation_config:
            return None
        kwargs: dict = {}
        if "response_mime_type" in generation_config:
            kwargs["response_mime_type"] = generation_config["response_mime_type"]
        if "response_schema" in generation_config:
            kwargs["response_schema"] = generation_config["response_schema"]
        if "temperature" in generation_config:
            kwargs["temperature"] = generation_config["temperature"]
        if "max_output_tokens" in generation_config:
            kwargs["max_output_tokens"] = generation_config["max_output_tokens"]
        if "top_p" in generation_config:
            kwargs["top_p"] = generation_config["top_p"]
        if "top_k" in generation_config:
            kwargs["top_k"] = generation_config["top_k"]
        if "stop_sequences" in generation_config:
            kwargs["stop_sequences"] = generation_config["stop_sequences"]
        return genai_types.GenerateContentConfig(**kwargs) if kwargs else None

    # ------------------------------------------------------------------
    # Public API (mirrors old GenerativeModel)
    # ------------------------------------------------------------------

    def generate_content(
        self,
        prompt: Any,
        *,
        generation_config: Optional[dict] = None,
        request_options: Optional[dict] = None,
        **_ignored: Any,
    ):
        """
        Generate content using the new google-genai SDK.

        Parameters mirror the old google.generativeai.GenerativeModel API:
        - prompt: str or list (multimodal parts)
        - generation_config: dict (response_mime_type, response_schema, …)
        - request_options: dict with optional 'timeout' key (seconds)
        """
        contents = self._build_contents(prompt)
        config = self._build_config(generation_config)

        http_options: Optional[genai_types.HttpOptions] = None
        if request_options and "timeout" in request_options:
            timeout_sec = request_options["timeout"]
            http_options = genai_types.HttpOptions(timeout=timeout_sec * 1000)  # ms
            if config is None:
                config = genai_types.GenerateContentConfig()
            config.http_options = http_options

        call_kwargs: dict[str, Any] = {
            "model": self._model_name,
            "contents": contents,
        }
        if config is not None:
            call_kwargs["config"] = config
        return self._client.models.generate_content(**call_kwargs)


def create_model(model_name: str, api_key: str) -> GeminiModel:
    """
    Create a GeminiModel adapter bound to a single API key.

    Using a per-call client ensures concurrent requests from different users
    never share credentials (replacing the old process-global genai.configure).
    """
    if not api_key:
        raise ValueError("A Gemini API key is required.")
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    return GeminiModel(model_name=model_name, client=client)
