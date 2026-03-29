"""Base LLM abstraction interface.

This module defines the abstract interface for LLM providers,
ensuring model-agnostic implementation per Constitution Principle IX.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    """Role of a message in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """A single message in a conversation."""

    role: MessageRole
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: Any = None


class LLMError(Exception):
    """Base exception for LLM-related errors."""

    pass


class LLMServiceUnavailableError(LLMError):
    """Raised when the LLM service is unavailable after retries."""

    pass


class LLMRateLimitError(LLMError):
    """Raised when rate limits are exceeded."""

    pass


class LLMAuthenticationError(LLMError):
    """Raised when authentication fails."""

    pass


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    All LLM integrations must implement this interface to ensure
    model-agnostic design per Constitution Principle IX.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion for the given messages.

        Args:
            messages: List of messages forming the conversation.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate (provider default if None).
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMResponse with the generated content.

        Raises:
            LLMServiceUnavailableError: If service unavailable after retries.
            LLMRateLimitError: If rate limits exceeded.
            LLMAuthenticationError: If authentication fails.
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model name/identifier."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'openai', 'gemini')."""
        pass
