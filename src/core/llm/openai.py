"""OpenAI LLM provider implementation."""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_fixed,
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


def _build_wait(retry_cfg: dict[str, Any]) -> Any:
    """Build a tenacity wait strategy from retry config."""
    backoff = retry_cfg.get("backoff", "exponential")
    delay = float(retry_cfg.get("delay_seconds", 2))
    if backoff == "fixed":
        return wait_fixed(delay)
    elif backoff == "linear":
        # wait_linear not available in all tenacity versions; use exponential as fallback
        return wait_exponential(multiplier=1, min=delay, max=delay * 10)
    else:  # exponential
        return wait_exponential(multiplier=1, min=delay, max=delay * 30)


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider with config-driven retry logic."""

    def __init__(
        self,
        model: str = "gpt-4o",
        retry_cfg: dict[str, Any] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """Initialize the OpenAI provider.

        Args:
            model: Model name (e.g. "gpt-4o-mini"). No provider prefix.
            retry_cfg: Retry config from agents.yaml retry block.
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var).
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
        self._retry_cfg = retry_cfg or {"max_attempts": 3, "backoff": "exponential", "delay_seconds": 2}
        self._client = AsyncOpenAI(api_key=self._api_key, base_url=base_url)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai"

    async def _call_api(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Any:
        """Make the actual API call."""
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
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using OpenAI.

        Args:
            messages: List of messages forming the conversation.
            temperature: Sampling temperature from agent config.
            max_tokens: Maximum output tokens from agent config.
            **kwargs: Additional OpenAI-specific parameters.

        Returns:
            LLMResponse with the generated content.
        """
        max_attempts = int(self._retry_cfg.get("max_attempts", 3))
        wait = _build_wait(self._retry_cfg)

        retry_decorator = retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait,
            retry=retry_if_exception_type((APIConnectionError, APIStatusError) if OPENAI_AVAILABLE else Exception),
            reraise=True,
        )
        call_with_retry = retry_decorator(self._call_api)

        openai_messages = [
            {"role": msg.role.value, "content": msg.content} for msg in messages
        ]

        try:
            response = await call_with_retry(
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
            logger.error(f"OpenAI service unavailable after {max_attempts} retries: {e}")
            raise LLMServiceUnavailableError(
                f"OpenAI service unavailable after {max_attempts} retries: {e}"
            )
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Unexpected error calling OpenAI: {e}")
