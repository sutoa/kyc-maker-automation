"""Integration tests for LangGraph workflow graph compilation."""

import pytest

from src.core.state import WorkflowState, create_initial_state
from src.core.workflow import (
    build_workflow_graph,
    compile_workflow,
    create_agent_node,
    create_critic_node,
    run_workflow_sync,
)
from src.models.enums import CriticDecision
from src.models.person import ClassifiedPerson, ExtractedPerson, ReconciledPerson, SourceReference
from src.services.document import DocumentInput, PageContent


# --- Test Fixtures ---


def create_test_document() -> DocumentInput:
    """Create a test document for workflow testing."""
    return DocumentInput(
        document_id="test_doc_1",
        filename="test_document.pdf",
        file_type="PDF",
        content="[PAGE 1]\nHans Müller, Geschäftsführer\nAnna Schmidt, Sachbearbeiterin",
        pages=[PageContent(page_number=1, text="Hans Müller, Geschäftsführer\nAnna Schmidt, Sachbearbeiterin")],
        page_count=1,
    )


def create_test_extracted_persons() -> list[ExtractedPerson]:
    """Create test extracted persons."""
    return [
        ExtractedPerson(
            extraction_id="ext_1",
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
            source_references=[
                SourceReference(
                    document_id="test_doc_1",
                    filename="test_document.pdf",
                    page_number=1,
                    extracted_text_snippet="Hans Müller, Geschäftsführer",
                    confidence=0.95,
                )
            ],
        ),
        ExtractedPerson(
            extraction_id="ext_2",
            first_name="Anna",
            last_name="Schmidt",
            job_title="Administrative Clerk",
            job_title_original="Sachbearbeiterin",
            source_references=[
                SourceReference(
                    document_id="test_doc_1",
                    filename="test_document.pdf",
                    page_number=1,
                    extracted_text_snippet="Anna Schmidt, Sachbearbeiterin",
                    confidence=0.90,
                )
            ],
        ),
    ]


def create_test_reconciled_persons() -> list[ReconciledPerson]:
    """Create test reconciled persons."""
    return [
        ReconciledPerson(
            person_id="person_1",
            first_name="Hans",
            last_name="Müller",
            first_name_normalized="hans",
            last_name_normalized="muller",
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
            source_references=[
                SourceReference(
                    document_id="test_doc_1",
                    filename="test_document.pdf",
                    page_number=1,
                )
            ],
        ),
        ReconciledPerson(
            person_id="person_2",
            first_name="Anna",
            last_name="Schmidt",
            first_name_normalized="anna",
            last_name_normalized="schmidt",
            job_title="Administrative Clerk",
            source_references=[
                SourceReference(
                    document_id="test_doc_1",
                    filename="test_document.pdf",
                    page_number=1,
                )
            ],
        ),
    ]


def create_test_classified_persons() -> list[ClassifiedPerson]:
    """Create test classified persons."""
    return [
        ClassifiedPerson(
            person_id="person_1",
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            source_references=[
                SourceReference(
                    document_id="test_doc_1",
                    filename="test_document.pdf",
                    page_number=1,
                )
            ],
            classification="CSM",
            reasoning="Managing Director (Geschäftsführer) is an executive role per Criterion 1.",
            criteria_met=["Criterion 1: Executive Management Role"],
        ),
        ClassifiedPerson(
            person_id="person_2",
            first_name="Anna",
            last_name="Schmidt",
            job_title="Administrative Clerk",
            source_references=[
                SourceReference(
                    document_id="test_doc_1",
                    filename="test_document.pdf",
                    page_number=1,
                )
            ],
            classification="NON_CSM",
            reasoning="Administrative Clerk has no executive authority.",
            criteria_not_met=["Criterion 1-5: No CSM criteria met"],
        ),
    ]


# --- Mock Agent Functions ---


def mock_extractor(state: WorkflowState) -> WorkflowState:
    """Mock extractor that returns test extracted persons."""
    return WorkflowState(
        **{
            **state,
            "extracted_persons": create_test_extracted_persons(),
        }
    )


def mock_reconciler(state: WorkflowState) -> WorkflowState:
    """Mock reconciler that returns test reconciled persons."""
    return WorkflowState(
        **{
            **state,
            "reconciled_persons": create_test_reconciled_persons(),
            "duplicate_groups": [],
        }
    )


def mock_classifier(state: WorkflowState) -> WorkflowState:
    """Mock classifier that returns test classified persons."""
    return WorkflowState(
        **{
            **state,
            "classified_persons": create_test_classified_persons(),
        }
    )


def mock_formatter(state: WorkflowState) -> WorkflowState:
    """Mock formatter that creates final output."""
    from src.models.output import DocumentManifestEntry

    classified = state.get("classified_persons", [])
    csm_list = [p for p in classified if p.classification == "CSM"]
    non_csm_list = [p for p in classified if p.classification == "NON_CSM"]

    return WorkflowState(
        **{
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
        }
    )


def mock_critic_pass(state: WorkflowState) -> tuple[CriticDecision, str | None]:
    """Mock critic that always passes."""
    return (CriticDecision.PASS, None)


def mock_critic_fail_once(fail_count: dict) -> callable:
    """Create a mock critic that fails once then passes."""
    def critic(state: WorkflowState) -> tuple[CriticDecision, str | None]:
        key = state.get("current_agent", "unknown")
        if fail_count.get(key, 0) == 0:
            fail_count[key] = 1
            return (CriticDecision.FAIL_RETRY, "Please retry with improvements")
        return (CriticDecision.PASS, None)
    return critic


# --- Test Classes ---


class TestBuildWorkflowGraph:
    """Tests for workflow graph building."""

    def test_build_graph_with_all_agents(self):
        """Test building graph with all required agents."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        graph = build_workflow_graph(agent_functions, critic_functions)

        # Verify graph was created
        assert graph is not None

    def test_build_graph_missing_agent_raises(self):
        """Test that missing agent raises ValueError."""
        agent_functions = {
            "extractor": mock_extractor,
            # Missing: reconciler, classifier, formatter
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        with pytest.raises(ValueError, match="Missing required agent"):
            build_workflow_graph(agent_functions, critic_functions)

    def test_build_graph_missing_critic_raises(self):
        """Test that missing critic raises ValueError."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            # Missing: critic_2, critic_3
        }

        with pytest.raises(ValueError, match="Missing required critic"):
            build_workflow_graph(agent_functions, critic_functions)


class TestCompileWorkflow:
    """Tests for workflow compilation."""

    def test_compile_workflow_succeeds(self):
        """Test that workflow compiles successfully."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)

        assert compiled is not None


class TestWorkflowExecution:
    """Tests for workflow execution."""

    def test_successful_workflow_execution(self):
        """Test complete successful workflow execution."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert len(final_state["csm_list"]) == 1
        assert len(final_state["non_csm_list"]) == 1
        assert final_state["csm_list"][0].first_name == "Hans"
        assert final_state["non_csm_list"][0].first_name == "Anna"

    def test_workflow_with_extraction_retry(self):
        """Test workflow with one extraction retry."""
        fail_count: dict = {}

        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_fail_once(fail_count),
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        # Should still complete after retry
        assert final_state["status"] == "completed"
        # Retry count should have incremented
        assert final_state.get("extraction_retry_count", 0) >= 1

    def test_workflow_preserves_workflow_id(self):
        """Test that workflow ID is preserved throughout execution."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state(
            [create_test_document()],
            workflow_id="test-workflow-123",
        )

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["workflow_id"] == "test-workflow-123"


class TestAgentNodeWrapper:
    """Tests for agent node wrapper."""

    def test_agent_wrapper_updates_current_agent(self):
        """Test that agent wrapper updates current_agent in state."""
        def simple_agent(state: WorkflowState) -> WorkflowState:
            return state

        wrapped = create_agent_node("test_agent", simple_agent, "next_agent")
        initial_state = create_initial_state([create_test_document()])

        result_state = wrapped(initial_state)

        assert result_state["current_agent"] == "next_agent"

    def test_agent_wrapper_handles_exception(self):
        """Test that agent wrapper handles exceptions gracefully."""
        def failing_agent(state: WorkflowState) -> WorkflowState:
            raise ValueError("Agent failed!")

        wrapped = create_agent_node("failing_agent", failing_agent)
        initial_state = create_initial_state([create_test_document()])

        result_state = wrapped(initial_state)

        assert result_state["status"] == "failed"
        assert "Agent failed" in (result_state.get("failure_reason") or "")


class TestCriticNodeWrapper:
    """Tests for critic node wrapper."""

    def test_critic_wrapper_handles_pass(self):
        """Test critic wrapper with PASS decision."""
        def passing_critic(state: WorkflowState) -> tuple[CriticDecision, str | None]:
            return (CriticDecision.PASS, None)

        wrapped = create_critic_node("critic_1", passing_critic, "extraction")
        initial_state = create_initial_state([create_test_document()])

        result_state = wrapped(initial_state)

        # Should move to next agent (reconciler)
        assert result_state["current_agent"] == "reconciler"
        assert result_state["extraction_feedback"] is None

    def test_critic_wrapper_handles_fail_retry(self):
        """Test critic wrapper with FAIL_RETRY decision."""
        def retrying_critic(state: WorkflowState) -> tuple[CriticDecision, str | None]:
            return (CriticDecision.FAIL_RETRY, "Please improve extraction")

        wrapped = create_critic_node("critic_1", retrying_critic, "extraction")
        initial_state = create_initial_state([create_test_document()])

        result_state = wrapped(initial_state)

        # Should retry extractor
        assert result_state["current_agent"] == "extractor"
        assert result_state["extraction_retry_count"] == 1
        assert result_state["extraction_feedback"] == "Please improve extraction"

    def test_critic_wrapper_handles_max_retries(self):
        """Test critic wrapper when max retries exceeded."""
        def retrying_critic(state: WorkflowState) -> tuple[CriticDecision, str | None]:
            return (CriticDecision.FAIL_RETRY, "Keep trying")

        wrapped = create_critic_node("critic_1", retrying_critic, "extraction")

        # Set retry count to max
        initial_state = create_initial_state([create_test_document()])
        initial_state = WorkflowState(**{**initial_state, "extraction_retry_count": 4})

        result_state = wrapped(initial_state)

        # Should fail workflow
        assert result_state["status"] == "failed"
        assert "Maximum retries" in (result_state.get("failure_reason") or "")


class TestWorkflowIntegration:
    """Integration tests for complete workflow scenarios."""

    def test_document_manifest_created(self):
        """Test that document manifest is created in output."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert len(final_state["document_manifest"]) == 1
        assert final_state["document_manifest"][0].filename == "test_document.pdf"
        assert final_state["document_manifest"][0].processing_status == "processed"

    def test_csm_classification_correct(self):
        """Test that CSM/NON_CSM classification is correct."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        # Hans Müller (Geschäftsführer) should be CSM
        csm_names = [p.first_name for p in final_state["csm_list"]]
        assert "Hans" in csm_names

        # Anna Schmidt (Sachbearbeiterin) should be NON_CSM
        non_csm_names = [p.first_name for p in final_state["non_csm_list"]]
        assert "Anna" in non_csm_names
