"""End-to-end smoke test for the extractor → critic → formatter workflow.

Uses unittest.mock to intercept LangChain ChatModel calls so no real API
key is needed. Verifies the full graph compiles and runs without error.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.state import create_initial_state
from src.core.workflow import compile_workflow, run_workflow
from src.models.person import ExtractedPerson
from src.models.workflow import ExtractorCriticFeedback
from src.services.document import DocumentInput, PageContent


def _doc(doc_id: str = "d1") -> DocumentInput:
    return DocumentInput(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        file_type="PDF",
        content="[PAGE 1]\nHans Müller, Geschäftsführer",
        pages=[PageContent(page_number=1, text="Hans Müller, Geschäftsführer")],
        page_count=1,
    )


def _mock_extractor_response():
    """Mock structured LLM output for the extractor."""
    mock = MagicMock()
    # Simulates _ListWrapper with items attribute
    mock.items = [
        ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
            doc_name="d1.pdf",
            page_number=1,
        )
    ]
    return mock


def _mock_critic_response():
    """Mock structured LLM output for the extractor_critic — pass."""
    return ExtractorCriticFeedback(
        status="pass",
        issues=[],
        feedback="All records valid.",
    )


def _mock_formatter_response():
    """Mock raw string LLM output for the formatter."""
    mock = MagicMock()
    mock.content = "# KYC Results\n\n## CSM List\n| First Name | Last Name |\n|---|---|\n| Hans | Müller |"
    return mock


@pytest.mark.asyncio
async def test_happy_path_extraction_to_formatter():
    """Full workflow: extract → critic passes → formatter → done."""

    call_count = {"n": 0}
    structured_mock = MagicMock()

    def invoke_side_effect(messages):
        call_count["n"] += 1
        n = call_count["n"]
        if n == 1:
            return _mock_extractor_response()   # extractor call
        if n == 2:
            return _mock_critic_response()       # extractor_critic call
        return MagicMock(content="fallback")

    structured_mock.invoke.side_effect = invoke_side_effect

    raw_mock = MagicMock()
    raw_mock.invoke.return_value = _mock_formatter_response()
    raw_mock.with_structured_output.return_value = structured_mock

    with patch("src.core.agent_factory._build_chat_model", return_value=raw_mock):
        compiled = compile_workflow()
        initial = create_initial_state([_doc()])
        final = await run_workflow(compiled, initial)

    assert final["status"] in ("completed", "in_progress")
    assert final.get("csm_report") is not None
    assert len(final["csm_report"]) > 0


@pytest.mark.asyncio
async def test_retry_then_pass():
    """Extractor fails critic once, succeeds on retry."""

    call_count = {"n": 0}
    structured_mock = MagicMock()
    raw_mock = MagicMock()

    def invoke_side_effect(messages):
        call_count["n"] += 1
        n = call_count["n"]
        if n in (1, 3):   # extractor runs twice
            return _mock_extractor_response()
        if n == 2:         # critic fails first time
            return ExtractorCriticFeedback(
                status="fail",
                issues=[],
                feedback="Missing job titles.",
            )
        if n == 4:         # critic passes second time
            return _mock_critic_response()
        return MagicMock(content="markdown")

    structured_mock.invoke.side_effect = invoke_side_effect
    raw_mock.invoke.return_value = _mock_formatter_response()
    raw_mock.with_structured_output.return_value = structured_mock

    with patch("src.core.agent_factory._build_chat_model", return_value=raw_mock):
        compiled = compile_workflow()
        initial = create_initial_state([_doc()])
        final = await run_workflow(compiled, initial)

    assert final.get("extraction_retry_count", 0) >= 1
