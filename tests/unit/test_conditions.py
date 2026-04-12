"""Unit tests for LangGraph routing functions."""

import pytest
from langgraph.graph import END
from langgraph.types import Command

from src.core.conditions import route_on_extractor_critic_decision
from src.core.state import WorkflowState, create_initial_state
from src.models.workflow import ExtractorCriticFeedback, ExtractionIssueSimple
from src.services.document import DocumentInput, PageContent


def _doc() -> DocumentInput:
    return DocumentInput(
        document_id="d1", filename="d1.pdf", file_type="PDF",
        content="text", pages=[PageContent(page_number=1, text="text")], page_count=1,
    )


def _pass_feedback() -> ExtractorCriticFeedback:
    return ExtractorCriticFeedback(status="pass", issues=[], feedback="All good.")


def _fail_feedback() -> ExtractorCriticFeedback:
    return ExtractorCriticFeedback(
        status="fail",
        issues=[ExtractionIssueSimple(
            first_name="Hans", last_name="Müller",
            issue_description="missing page", severity="error",
        )],
        feedback="Fix missing page numbers.",
    )


class TestRouteOnExtractorCriticDecision:
    def test_pass_routes_to_formatter(self):
        state = create_initial_state([_doc()])
        state["extractor_critic_feedback"] = _pass_feedback()
        cmd = route_on_extractor_critic_decision(state)
        assert isinstance(cmd, Command)
        assert cmd.goto == "formatter"

    def test_no_feedback_defaults_to_pass(self):
        state = create_initial_state([_doc()])
        # extractor_critic_feedback is None
        cmd = route_on_extractor_critic_decision(state)
        assert cmd.goto == "formatter"

    def test_fail_with_retries_remaining_goes_to_extractor(self):
        state = create_initial_state([_doc()])
        state["extractor_critic_feedback"] = _fail_feedback()
        state["extraction_retry_count"] = 2
        cmd = route_on_extractor_critic_decision(state)
        assert cmd.goto == "extractor"

    def test_fail_increments_retry_count(self):
        state = create_initial_state([_doc()])
        state["extractor_critic_feedback"] = _fail_feedback()
        state["extraction_retry_count"] = 1
        cmd = route_on_extractor_critic_decision(state)
        assert cmd.update == {"extraction_retry_count": 2}

    def test_fail_at_max_retries_goes_to_end(self):
        state = create_initial_state([_doc()])
        state["extractor_critic_feedback"] = _fail_feedback()
        state["extraction_retry_count"] = 4
        cmd = route_on_extractor_critic_decision(state)
        assert cmd.goto == END

    def test_fail_at_max_retries_no_state_update(self):
        state = create_initial_state([_doc()])
        state["extractor_critic_feedback"] = _fail_feedback()
        state["extraction_retry_count"] = 4
        cmd = route_on_extractor_critic_decision(state)
        assert not cmd.update  # no increment when halting
