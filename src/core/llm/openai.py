"""OpenAI LLM provider implementation.

This module implements the LLMProvider interface for OpenAI models
with exponential backoff retry logic (3 attempts).
"""

import os
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .base import (
    LLMAuthenticationError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMServiceUnavailableError,
    Message,
)

try:
    from openai import (
        APIConnectionError,
        APIStatusError,
        AsyncOpenAI,
        AuthenticationError,
        RateLimitError,
    )
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider with retry logic.

    Implements exponential backoff retry (3 attempts) for transient failures.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o",
        base_url: str | None = None,
    ):
        """Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var).
            model: Model to use (default: gpt-4o).
            base_url: Optional custom base URL for API.
        """
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "openai package not installed. Install with: pip install openai"
            )

        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise LLMAuthenticationError("OPENAI_API_KEY not set")

        self._model = model
        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=base_url,
        )

    @property
    def model_name(self) -> str:
        """Return the model name."""
        return self._model

    @property
    def provider_name(self) -> str:
        """Return the provider name."""
        return "openai"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((APIConnectionError, APIStatusError)),
        reraise=True,
    )
    async def _call_api(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> Any:
        """Make the actual API call with retry logic."""
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return response
        except AuthenticationError as e:
            raise LLMAuthenticationError(f"OpenAI authentication failed: {e}")
        except RateLimitError as e:
            raise LLMRateLimitError(f"OpenAI rate limit exceeded: {e}")

    async def complete(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using OpenAI.

        Args:
            messages: List of messages forming the conversation.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional OpenAI-specific parameters.

        Returns:
            LLMResponse with the generated content.
        """
        # Convert messages to OpenAI format
        openai_messages = [
            {"role": msg.role.value, "content": msg.content} for msg in messages
        ]

        try:
            response = await self._call_api(
                messages=openai_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            return LLMResponse(
                content=response.choices[0].message.content or "",
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
                raw_response=response,
            )
        except (APIConnectionError, APIStatusError) as e:
            # After 3 retries, convert to service unavailable
            raise LLMServiceUnavailableError(
                f"OpenAI service unavailable after 3 retries: {e}"
            )
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Unexpected error calling OpenAI: {e}")
