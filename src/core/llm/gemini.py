"""Google Gemini LLM provider implementation.

This module implements the LLMProvider interface for Google Gemini models
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


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider with retry logic.

    Implements exponential backoff retry (3 attempts) for transient failures.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-1.5-pro",
    ):
        """Initialize the Gemini provider.

        Args:
            api_key: Google API key (defaults to GOOGLE_API_KEY env var).
            model: Model to use (default: gemini-1.5-pro).
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
        genai.configure(api_key=self._api_key)
        self._model = genai.GenerativeModel(model)

    @property
    def model_name(self) -> str:
        """Return the model name."""
        return self._model_name

    @property
    def provider_name(self) -> str:
        """Return the provider name."""
        return "gemini"

    def _convert_messages_to_gemini_format(
        self, messages: list[Message]
    ) -> tuple[str | None, list[dict[str, str]]]:
        """Convert messages to Gemini's format.

        Gemini uses a different format:
        - System message is passed separately
        - History is a list of content dicts with 'role' and 'parts'

        Returns:
            Tuple of (system_instruction, history)
        """
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(
            GoogleAPICallError if GEMINI_AVAILABLE else Exception
        ),
        reraise=True,
    )
    async def _call_api(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> Any:
        """Make the actual API call with retry logic."""
        try:
            system_instruction, history = self._convert_messages_to_gemini_format(messages)

            # Create a new model instance with system instruction if provided
            if system_instruction:
                model = genai.GenerativeModel(
                    self._model_name,
                    system_instruction=system_instruction,
                )
            else:
                model = self._model

            # Configure generation parameters
            generation_config = genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )

            # Start a chat with history if there are multiple messages
            if len(history) > 1:
                chat = model.start_chat(history=history[:-1])
                # Send the last message
                last_message = history[-1]["parts"][0] if history else ""
                response = await chat.send_message_async(
                    last_message,
                    generation_config=generation_config,
                )
            elif history:
                # Single message
                response = await model.generate_content_async(
                    history[0]["parts"][0],
                    generation_config=generation_config,
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
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using Gemini.

        Args:
            messages: List of messages forming the conversation.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional Gemini-specific parameters.

        Returns:
            LLMResponse with the generated content.
        """
        try:
            response = await self._call_api(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            # Extract text from response
            content = ""
            if hasattr(response, "text"):
                content = response.text
            elif hasattr(response, "parts"):
                content = "".join(part.text for part in response.parts if hasattr(part, "text"))

            # Extract usage if available
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
            # After 3 retries, convert to service unavailable
            raise LLMServiceUnavailableError(
                f"Gemini service unavailable after 3 retries: {e}"
            )
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Unexpected error calling Gemini: {e}")
