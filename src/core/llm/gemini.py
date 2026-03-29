"""Google Gemini LLM provider implementation."""

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
    MessageRole,
)

try:
    import google.generativeai as genai
    from google.api_core.exceptions import (
        GoogleAPICallError,
        ResourceExhausted,
        Unauthenticated,
    )
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


def _build_wait(retry_cfg: dict[str, Any]) -> Any:
    """Build a tenacity wait strategy from retry config."""
    backoff = retry_cfg.get("backoff", "exponential")
    delay = float(retry_cfg.get("delay_seconds", 2))
    if backoff == "fixed":
        return wait_fixed(delay)
    elif backoff == "linear":
        return wait_linear(min=delay, max=delay * 10)
    else:  # exponential
        return wait_exponential(multiplier=1, min=delay, max=delay * 30)


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider with config-driven retry logic."""

    def __init__(
        self,
        model: str = "gemini-1.5-pro",
        retry_cfg: dict[str, Any] | None = None,
        api_key: str | None = None,
    ):
        """Initialize the Gemini provider.

        Args:
            model: Model name (e.g. "gemini-1.5-pro"). No provider prefix.
            retry_cfg: Retry config from agents.yaml retry block.
            api_key: Google API key (defaults to GOOGLE_API_KEY env var).
        """
        if not GEMINI_AVAILABLE:
            raise ImportError(
                "google-generativeai package not installed. "
                "Install with: pip install google-generativeai"
            )

        self._api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self._api_key:
            raise LLMAuthenticationError("GOOGLE_API_KEY not set")

        self._model_name = model
        self._retry_cfg = retry_cfg or {"max_attempts": 3, "backoff": "exponential", "delay_seconds": 2}
        genai.configure(api_key=self._api_key)
        self._model = genai.GenerativeModel(model)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _convert_messages_to_gemini_format(
        self, messages: list[Message]
    ) -> tuple[str | None, list[dict[str, str]]]:
        """Convert messages to Gemini's format (system instruction + history)."""
        system_instruction = None
        history = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_instruction = msg.content
            elif msg.role == MessageRole.USER:
                history.append({"role": "user", "parts": [msg.content]})
            elif msg.role == MessageRole.ASSISTANT:
                history.append({"role": "model", "parts": [msg.content]})
        return system_instruction, history

    async def _call_api(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Any:
        """Make the actual API call."""
        try:
            system_instruction, history = self._convert_messages_to_gemini_format(messages)

            model = (
                genai.GenerativeModel(self._model_name, system_instruction=system_instruction)
                if system_instruction
                else self._model
            )

            generation_config = genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )

            if len(history) > 1:
                chat = model.start_chat(history=history[:-1])
                last_message = history[-1]["parts"][0] if history else ""
                response = await chat.send_message_async(last_message, generation_config=generation_config)
            elif history:
                response = await model.generate_content_async(
                    history[0]["parts"][0], generation_config=generation_config
                )
            else:
                raise LLMError("No messages provided")

            return response

        except Unauthenticated as e:
            raise LLMAuthenticationError(f"Gemini authentication failed: {e}")
        except ResourceExhausted as e:
            raise LLMRateLimitError(f"Gemini rate limit exceeded: {e}")

    async def complete(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using Gemini.

        Args:
            messages: List of messages forming the conversation.
            temperature: Sampling temperature from agent config.
            max_tokens: Maximum output tokens from agent config.
            **kwargs: Additional Gemini-specific parameters.

        Returns:
            LLMResponse with the generated content.
        """
        max_attempts = int(self._retry_cfg.get("max_attempts", 3))
        wait = _build_wait(self._retry_cfg)

        retry_decorator = retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait,
            retry=retry_if_exception_type(
                GoogleAPICallError if GEMINI_AVAILABLE else Exception
            ),
            reraise=True,
        )
        call_with_retry = retry_decorator(self._call_api)

        try:
            response = await call_with_retry(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            content = ""
            if hasattr(response, "text"):
                content = response.text
            elif hasattr(response, "parts"):
                content = "".join(p.text for p in response.parts if hasattr(p, "text"))

            usage = {}
            if hasattr(response, "usage_metadata"):
                meta = response.usage_metadata
                usage = {
                    "prompt_tokens": getattr(meta, "prompt_token_count", 0),
                    "completion_tokens": getattr(meta, "candidates_token_count", 0),
                    "total_tokens": getattr(meta, "total_token_count", 0),
                }

            return LLMResponse(
                content=content,
                model=self._model_name,
                usage=usage,
                raw_response=response,
            )

        except GoogleAPICallError as e:
            logger.error(f"Gemini service unavailable after {max_attempts} retries: {e}")
            raise LLMServiceUnavailableError(
                f"Gemini service unavailable after {max_attempts} retries: {e}"
            )
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Unexpected error calling Gemini: {e}")
