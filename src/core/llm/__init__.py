"""Model-agnostic LLM abstraction layer (Constitution Principle IX).

This module provides a provider-agnostic interface for LLM interactions,
allowing easy switching between OpenAI and Gemini based on configuration.

Usage:
    from src.core.llm import get_llm_provider, Message, MessageRole

    provider = get_llm_provider()  # Uses LLM_PROVIDER env var
    response = await provider.complete([
        Message(role=MessageRole.SYSTEM, content="You are a helpful assistant."),
        Message(role=MessageRole.USER, content="Hello!"),
    ])
"""

import os
from typing import Literal

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
    provider: Literal["openai", "gemini"] | None = None,
    **kwargs,
) -> LLMProvider:
    """Factory function to get an LLM provider.

    Args:
        provider: Provider name ('openai' or 'gemini').
                  Defaults to LLM_PROVIDER env var, then 'openai'.
        **kwargs: Additional provider-specific configuration.

    Returns:
        LLMProvider instance for the specified provider.

    Raises:
        ValueError: If provider is not supported.
        LLMAuthenticationError: If required API key is not set.
    """
    if provider is None:
        provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if provider == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(**kwargs)
    elif provider == "gemini":
        from .gemini import GeminiProvider
        return GeminiProvider(**kwargs)
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            "Supported providers: openai, gemini"
        )


__all__ = [
    # Factory
    "get_llm_provider",
    # Base classes and types
    "LLMProvider",
    "LLMResponse",
    "Message",
    "MessageRole",
    # Errors
    "LLMError",
    "LLMAuthenticationError",
    "LLMRateLimitError",
    "LLMServiceUnavailableError",
]
