"""Integration tests for LangGraph workflow graph compilation.

These tests wire up mock agent functions that match the factory contract
(state: WorkflowState) -> WorkflowState, then build and run the graph
using the YAML topology from workflows.yaml.  The LLM layer is never called.
"""

from typing import Any

import pytest

from src.config.loader import load_workflows_config
from src.core.state import WorkflowState, create_initial_state
from src.core.workflow import (
    build_workflow_graph,
    create_agent_node,
    run_workflow_sync,
)
from src.models.output import DocumentManifestEntry
from src.models.person import ClassifiedPerson, ExtractedPerson, ReconciledPerson, SourceReference
from src.models.workflow import ExtractorCriticFeedback, ExtractionIssueSimple
from src.services.document import DocumentInput, PageContent


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def create_test_document() -> DocumentInput:
    return DocumentInput(
        document_id="test_doc_1",
        filename="test_document.pdf",
        file_type="PDF",
        content="[PAGE 1]\nHans Müller, Geschäftsführer\nAnna Schmidt, Sachbearbeiterin",
        pages=[PageContent(page_number=1, text="Hans Müller, Geschäftsführer\nAnna Schmidt, Sachbearbeiterin")],
        page_count=1,
    )


def create_test_extracted_persons() -> list[ExtractedPerson]:
    return [
        ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
            doc_name="test_document.pdf",
            page_number=1,
        ),
        ExtractedPerson(
            first_name="Anna",
            last_name="Schmidt",
            job_title="Administrative Clerk",
            job_title_original="Sachbearbeiterin",
            doc_name="test_document.pdf",
            page_number=1,
        ),
    ]


def create_test_reconciled_persons() -> list[ReconciledPerson]:
    return [
        ReconciledPerson(
            person_id="person_1",
            first_name="Hans",
            last_name="Müller",
            first_name_normalized="hans",
            last_name_normalized="muller",
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
            source_references=[SourceReference(document_id="test_doc_1", filename="test_document.pdf", page_number=1)],
        ),
        ReconciledPerson(
            person_id="person_2",
            first_name="Anna",
            last_name="Schmidt",
            first_name_normalized="anna",
            last_name_normalized="schmidt",
            job_title="Administrative Clerk",
            source_references=[SourceReference(document_id="test_doc_1", filename="test_document.pdf", page_number=1)],
        ),
    ]


def create_test_classified_persons() -> list[ClassifiedPerson]:
    return [
        ClassifiedPerson(
            person_id="person_1",
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            source_references=[SourceReference(document_id="test_doc_1", filename="test_document.pdf", page_number=1)],
            classification="CSM",
            reasoning="Managing Director (Geschäftsführer) is an executive role per Criterion 1.",
            criteria_met=["Criterion 1: Executive Management Role"],
        ),
        ClassifiedPerson(
            person_id="person_2",
            first_name="Anna",
            last_name="Schmidt",
            job_title="Administrative Clerk",
            source_references=[SourceReference(document_id="test_doc_1", filename="test_document.pdf", page_number=1)],
            classification="NON_CSM",
            reasoning="Administrative Clerk has no executive authority.",
            criteria_not_met=["Criterion 1-5: No CSM criteria met"],
        ),
    ]


# ---------------------------------------------------------------------------
# Mock agent functions — factory contract: (state) -> WorkflowState
# ---------------------------------------------------------------------------


def mock_extractor(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "extracted_persons": create_test_extracted_persons()})


def mock_reconciler(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "reconciled_persons": create_test_reconciled_persons(), "duplicate_groups": []})


def mock_classifier(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "classified_persons": create_test_classified_persons()})


def mock_formatter(state: WorkflowState) -> WorkflowState:
    extracted = state.get("extracted_persons", [])
    executive_terms = ["director", "managing", "ceo", "chief", "executive", "vorstand"]
    csm_list = []
    non_csm_list = []
    for ep in extracted:
        title = (ep.job_title or "").lower()
        if any(t in title for t in executive_terms):
            csm_list.append(ClassifiedPerson(
                person_id=f"p_{ep.first_name}",
                first_name=ep.first_name,
                last_name=ep.last_name,
                job_title=ep.job_title,
                source_references=[],
                classification="CSM",
                reasoning="Executive role.",
                criteria_met=["Criterion 1: Executive Management Role"],
            ))
        else:
            non_csm_list.append(ClassifiedPerson(
                person_id=f"p_{ep.first_name}",
                first_name=ep.first_name,
                last_name=ep.last_name,
                job_title=ep.job_title,
                source_references=[],
                classification="NON_CSM",
                reasoning="No executive role.",
                criteria_not_met=["Criterion 1-5: No CSM criteria met"],
            ))
    return WorkflowState(**{
        **state,
        "document_manifest": [
            DocumentManifestEntry(
                filename="test_document.pdf",
                file_type="PDF",
                page_count=1,
                processing_status="processed",
            )
        ],
        "csm_list": csm_list,
        "non_csm_list": non_csm_list,
        "status": "completed",
        "current_agent": "",
    })


def _pass_extractor_feedback() -> ExtractorCriticFeedback:
    return ExtractorCriticFeedback(status="pass", issues=[], feedback="All records valid.")


def _fail_extractor_feedback(message: str) -> ExtractorCriticFeedback:
    return ExtractorCriticFeedback(
        status="fail",
        issues=[ExtractionIssueSimple(
            first_name="?", last_name="?",
            issue_description=message,
            severity="error",
        )],
        feedback=message,
    )


def mock_critic_1_pass(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "extractor_critic_feedback": _pass_extractor_feedback()})


def mock_critic_2_pass(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "last_critic_feedback": None})


def mock_critic_3_pass(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "last_critic_feedback": None})


def make_critic_1_fail_once() -> tuple[Any, list[int]]:
    """Return (critic_1 mock, call_counter) that fails once then passes."""
    calls: list[int] = [0]

    def critic_fn(state: WorkflowState) -> WorkflowState:
        calls[0] += 1
        if calls[0] == 1:
            fb = _fail_extractor_feedback("Please retry with improvements")
        else:
            fb = _pass_extractor_feedback()
        return WorkflowState(**{**state, "extractor_critic_feedback": fb})

    return critic_fn, calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_mock_graph(
    extractor_fn=mock_extractor,
    critic_1_fn=mock_critic_1_pass,
    reconciler_fn=mock_reconciler,
    critic_2_fn=mock_critic_2_pass,
    classifier_fn=mock_classifier,
    critic_3_fn=mock_critic_3_pass,
    formatter_fn=mock_formatter,
):
    """Build a compiled workflow with injected mock functions."""
    workflows_config = load_workflows_config()
    functions = {
        "extractor": extractor_fn,
        "critic_1": critic_1_fn,
        "reconciler": reconciler_fn,
        "critic_2": critic_2_fn,
        "classifier": classifier_fn,
        "critic_3": critic_3_fn,
        "formatter": formatter_fn,
    }
    graph = build_workflow_graph(functions, workflows_config)
    return graph.compile()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildWorkflowGraph:
    """Tests for workflow graph building."""

    def test_build_graph_with_all_agents(self):
        """Test building graph with all required agents."""
        compiled = build_mock_graph()
        assert compiled is not None

    def test_build_graph_missing_node_raises(self):
        """Test that missing node function raises ValueError."""
        workflows_config = load_workflows_config()
        functions = {
            "extractor": mock_extractor,
            # Missing: critic_1, reconciler, critic_2, classifier, critic_3, formatter
        }
        with pytest.raises(ValueError, match="no matching function"):
            build_workflow_graph(functions, workflows_config)


class TestWorkflowExecution:
    """Tests for workflow execution."""

    def test_successful_workflow_execution(self):
        """Test complete successful workflow execution."""
        compiled = build_mock_graph()
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert len(final_state["csm_list"]) == 1
        assert len(final_state["non_csm_list"]) == 1
        assert final_state["csm_list"][0].first_name == "Hans"
        assert final_state["non_csm_list"][0].first_name == "Anna"

    def test_workflow_with_extraction_retry(self):
        """Test workflow with one extraction retry (critic fails once then passes)."""
        critic_fn, call_counter = make_critic_1_fail_once()
        compiled = build_mock_graph(critic_1_fn=critic_fn)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        # critic_1 was called twice: once FAIL_RETRY, once PASS
        assert call_counter[0] >= 2

    def test_workflow_preserves_workflow_id(self):
        """Test that workflow ID is preserved throughout execution."""
        compiled = build_mock_graph()
        initial_state = create_initial_state(
            [create_test_document()],
            workflow_id="test-workflow-123",
        )

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["workflow_id"] == "test-workflow-123"


class TestAgentNodeWrapper:
    """Tests for agent node wrapper."""

    def test_agent_wrapper_updates_current_agent(self):
        """Test that agent wrapper sets current_agent to the running agent's name."""
        def simple_agent(state: WorkflowState) -> WorkflowState:
            return state

        wrapped = create_agent_node("test_agent", simple_agent)
        initial_state = create_initial_state([create_test_document()])

        result_state = wrapped(initial_state)

        assert result_state["current_agent"] == "test_agent"

    def test_agent_wrapper_handles_exception(self):
        """Test that agent wrapper handles exceptions gracefully."""
        def failing_agent(state: WorkflowState) -> WorkflowState:
            raise ValueError("Agent failed!")

        wrapped = create_agent_node("failing_agent", failing_agent)
        initial_state = create_initial_state([create_test_document()])

        result_state = wrapped(initial_state)

        assert result_state["status"] == "failed"
        assert "Agent failed" in (result_state.get("failure_reason") or "")


class TestWorkflowIntegration:
    """Integration tests for complete workflow scenarios."""

    def test_document_manifest_created(self):
        """Test that document manifest is created in output."""
        compiled = build_mock_graph()
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert len(final_state["document_manifest"]) == 1
        assert final_state["document_manifest"][0].filename == "test_document.pdf"
        assert final_state["document_manifest"][0].processing_status == "processed"

    def test_csm_classification_correct(self):
        """Test that CSM/NON_CSM classification is correct."""
        compiled = build_mock_graph()
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        csm_names = [p.first_name for p in final_state["csm_list"]]
        assert "Hans" in csm_names

        non_csm_names = [p.first_name for p in final_state["non_csm_list"]]
        assert "Anna" in non_csm_names
