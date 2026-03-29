"""Unit tests for LLM abstraction layer."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.llm import (
    LLMAuthenticationError,
    LLMProvider,
    LLMResponse,
    Message,
    MessageRole,
    get_llm_provider,
)
from src.core.llm.base import LLMServiceUnavailableError

# Check if google-generativeai is available
try:
    import google.generativeai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

gemini_required = pytest.mark.skipif(
    not GEMINI_AVAILABLE,
    reason="google-generativeai package not installed"
)


class TestMessage:
    """Tests for Message dataclass."""

    def test_create_system_message(self):
        """Test creating a system message."""
        msg = Message(role=MessageRole.SYSTEM, content="You are an assistant.")
        assert msg.role == MessageRole.SYSTEM
        assert msg.content == "You are an assistant."

    def test_create_user_message(self):
        """Test creating a user message."""
        msg = Message(role=MessageRole.USER, content="Hello!")
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello!"

    def test_create_assistant_message(self):
        """Test creating an assistant message."""
        msg = Message(role=MessageRole.ASSISTANT, content="Hi there!")
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "Hi there!"


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_create_response(self):
        """Test creating an LLM response."""
        response = LLMResponse(
            content="Hello, how can I help?",
            model="gpt-4o",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )
        assert response.content == "Hello, how can I help?"
        assert response.model == "gpt-4o"
        assert response.usage["total_tokens"] == 30

    def test_response_default_usage(self):
        """Test that usage defaults to empty dict."""
        response = LLMResponse(content="test", model="test-model")
        assert response.usage == {}


class TestGetLLMProvider:
    """Tests for get_llm_provider factory function."""

    def test_invalid_provider(self):
        """Test that invalid provider raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            get_llm_provider("invalid/model")

    @patch.dict(os.environ, {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-key"})
    def test_default_provider_from_env(self):
        """Test that provider is resolved from LLM_PROVIDER env var when no prefix given."""
        provider = get_llm_provider("gpt-4o")
        assert provider.provider_name == "openai"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True)
    def test_default_to_openai(self):
        """Test that OpenAI is the default when no env var set."""
        os.environ.pop("LLM_PROVIDER", None)
        provider = get_llm_provider("gpt-4o")
        assert provider.provider_name == "openai"


class TestOpenAIProvider:
    """Tests for OpenAI provider."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_create_provider(self):
        """Test creating OpenAI provider."""
        from src.core.llm.openai import OpenAIProvider

        provider = OpenAIProvider()
        assert provider.provider_name == "openai"
        assert provider.model_name == "gpt-4o"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_create_provider_custom_model(self):
        """Test creating OpenAI provider with custom model."""
        from src.core.llm.openai import OpenAIProvider

        provider = OpenAIProvider(model="gpt-4o-mini")
        assert provider.model_name == "gpt-4o-mini"

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key(self):
        """Test that missing API key raises error."""
        from src.core.llm.openai import OpenAIProvider

        os.environ.pop("OPENAI_API_KEY", None)
        with pytest.raises(LLMAuthenticationError, match="OPENAI_API_KEY not set"):
            OpenAIProvider()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    async def test_complete_success(self):
        """Test successful completion."""
        from src.core.llm.openai import OpenAIProvider

        provider = OpenAIProvider()

        # Mock the OpenAI client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello, I'm an AI assistant."
        mock_response.model = "gpt-4o"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 15
        mock_response.usage.total_tokens = 25

        provider._client.chat.completions.create = AsyncMock(return_value=mock_response)

        messages = [
            Message(role=MessageRole.USER, content="Hello"),
        ]
        response = await provider.complete(messages, temperature=0, max_tokens=100)

        assert response.content == "Hello, I'm an AI assistant."
        assert response.model == "gpt-4o"
        assert response.usage["total_tokens"] == 25


class TestGeminiProvider:
    """Tests for Gemini provider."""

    @gemini_required
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_create_provider(self, mock_model, mock_configure):
        """Test creating Gemini provider."""
        from src.core.llm.gemini import GeminiProvider

        provider = GeminiProvider()
        assert provider.provider_name == "gemini"
        assert provider.model_name == "gemini-1.5-pro"
        mock_configure.assert_called_once_with(api_key="test-key")

    @gemini_required
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_create_provider_custom_model(self, mock_model, mock_configure):
        """Test creating Gemini provider with custom model."""
        from src.core.llm.gemini import GeminiProvider

        provider = GeminiProvider(model="gemini-1.5-flash")
        assert provider.model_name == "gemini-1.5-flash"

    @gemini_required
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key(self):
        """Test that missing API key raises error."""
        from src.core.llm.gemini import GeminiProvider

        os.environ.pop("GOOGLE_API_KEY", None)
        with pytest.raises(LLMAuthenticationError, match="GOOGLE_API_KEY not set"):
            GeminiProvider()


class TestLLMProviderInterface:
    """Tests to verify LLMProvider interface compliance."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_openai_implements_interface(self):
        """Test that OpenAI provider implements LLMProvider interface."""
        from src.core.llm.openai import OpenAIProvider

        provider = OpenAIProvider()
        assert isinstance(provider, LLMProvider)
        assert hasattr(provider, "complete")
        assert hasattr(provider, "model_name")
        assert hasattr(provider, "provider_name")

    @gemini_required
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_gemini_implements_interface(self, mock_model, mock_configure):
        """Test that Gemini provider implements LLMProvider interface."""
        from src.core.llm.gemini import GeminiProvider

        provider = GeminiProvider()
        assert isinstance(provider, LLMProvider)
        assert hasattr(provider, "complete")
        assert hasattr(provider, "model_name")
        assert hasattr(provider, "provider_name")
