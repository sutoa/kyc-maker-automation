"""Unit tests for the agent factory."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from src.core.agent_factory import _build_chat_model, build_agent_fn
from src.core.state import WorkflowState, create_initial_state
from src.services.document import DocumentInput, PageContent


def _doc() -> DocumentInput:
    return DocumentInput(
        document_id="d1", filename="d1.pdf", file_type="PDF",
        content="text", pages=[PageContent(page_number=1, text="text")], page_count=1,
    )


AGENTS_DIR = Path("src/config")


class SimpleOutput(BaseModel):
    value: str


class TestBuildChatModel:
    def test_openai_provider(self):
        with patch("src.core.agent_factory.ChatOpenAI") as mock_cls:
            _build_chat_model("openai/gpt-4o-mini", temperature=0, max_tokens=100)
            mock_cls.assert_called_once_with(
                model="gpt-4o-mini", temperature=0, max_tokens=100
            )

    def test_gemini_provider(self):
        with patch("src.core.agent_factory.ChatGoogleGenerativeAI") as mock_cls:
            _build_chat_model("gemini/gemini-2.0-flash", temperature=0.5, max_tokens=512)
            mock_cls.assert_called_once_with(
                model="gemini-2.0-flash", temperature=0.5, max_tokens=512
            )

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            _build_chat_model("anthropic/claude-3", temperature=0, max_tokens=100)


class TestBuildLLMAgentFn:
    def test_agent_with_schema_calls_structured_output(self):
        cfg = {
            "execution": "llm",
            "role": "Tester",
            "goal": "Test",
            "backstory": "Testing.",
            "model": "openai/gpt-4o-mini",
            "temperature": 0,
            "max_tokens": 100,
            "input_keys": [],
            "output_key": "test_output",
            "system_prompt": {"inline": "You are a test agent."},
            "output_schema": {"ref": "tests.unit.test_agent_factory.SimpleOutput", "is_list": False},
            "retry": {"max_attempts": 4},
        }
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = SimpleOutput(value="hello")
        mock_llm.with_structured_output.return_value = mock_structured

        with patch("src.core.agent_factory._build_chat_model", return_value=mock_llm):
            fn = build_agent_fn("test_agent", cfg, AGENTS_DIR)
            state = create_initial_state([_doc()])
            result = fn(state)

        assert result["test_output"] == SimpleOutput(value="hello")
        mock_llm.with_structured_output.assert_called_once()

    def test_agent_without_schema_returns_raw_string(self):
        cfg = {
            "execution": "llm",
            "role": "Formatter",
            "goal": "Format",
            "backstory": "Formatting.",
            "model": "openai/gpt-4o-mini",
            "temperature": 0,
            "max_tokens": 1000,
            "input_keys": [],
            "output_key": "csm_report",
            "system_prompt": {"inline": "Format this."},
            "retry": {"max_attempts": 4},
            # no output_schema
        }
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "# KYC Report\n..."
        mock_llm.invoke.return_value = mock_response

        with patch("src.core.agent_factory._build_chat_model", return_value=mock_llm):
            fn = build_agent_fn("formatter", cfg, AGENTS_DIR)
            state = create_initial_state([_doc()])
            result = fn(state)

        assert result["csm_report"] == "# KYC Report\n..."
        mock_llm.with_structured_output.assert_not_called()
