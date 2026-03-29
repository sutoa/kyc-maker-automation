"""Model-agnostic LLM abstraction layer.

Provides a provider-agnostic interface for LLM interactions.
The model string follows LiteLLM format: "provider/model-name"
e.g. "openai/gpt-4o-mini", "gemini/gemini-1.5-pro".

Usage:
    from src.core.llm import get_llm_provider

    provider = get_llm_provider(
        model_string="openai/gpt-4o-mini",
        retry_cfg={"max_attempts": 4, "backoff": "exponential", "delay_seconds": 1},
    )
    response = await provider.complete(
        messages=[...],
        temperature=0,
        max_tokens=16384,
    )
"""

import os
from typing import Any

from .base import (
    LLMAuthenticationError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMServiceUnavailableError,
    Message,
    MessageRole,
)


def get_llm_provider(
    model_string: str,
    retry_cfg: dict[str, Any] | None = None,
) -> LLMProvider:
    """Factory function to get an LLM provider from a LiteLLM-style model string.

    Args:
        model_string: LiteLLM format string "provider/model-name",
                      e.g. "openai/gpt-4o-mini" or "gemini/gemini-1.5-pro".
                      Falls back to LLM_PROVIDER env var + model if no "/" present.
        retry_cfg: Retry configuration dict with keys:
                   max_attempts (int), backoff (linear|exponential|fixed),
                   delay_seconds (float). Defaults to 3 attempts, exponential, 2s.

    Returns:
        LLMProvider instance configured for the specified provider and model.

    Raises:
        ValueError: If provider is not supported or model_string is invalid.
        LLMAuthenticationError: If required API key is not set.
    """
    retry_cfg = retry_cfg or {"max_attempts": 3, "backoff": "exponential", "delay_seconds": 2}

    if "/" in model_string:
        provider, model_name = model_string.split("/", 1)
    else:
        provider = os.getenv("LLM_PROVIDER", "openai").lower()
        model_name = model_string

    provider = provider.lower()

    if provider == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(model=model_name, retry_cfg=retry_cfg)
    elif provider == "gemini":
        from .gemini import GeminiProvider
        return GeminiProvider(model=model_name, retry_cfg=retry_cfg)
    else:
        raise ValueError(
            f"Unsupported LLM provider: '{provider}'. "
            "Supported providers: openai, gemini"
        )


__all__ = [
    "get_llm_provider",
    "LLMProvider",
    "LLMResponse",
    "Message",
    "MessageRole",
    "LLMError",
    "LLMAuthenticationError",
    "LLMRateLimitError",
    "LLMServiceUnavailableError",
]
