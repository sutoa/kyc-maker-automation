"""Shared mock helpers for integration tests.

All mock agent functions follow the factory contract:
    (state: WorkflowState) -> WorkflowState

Critics write a CriticFeedback object to `last_critic_feedback`.
"""

from datetime import datetime
from uuid import uuid4

from src.config.loader import load_workflows_config
from src.core.state import WorkflowState
from src.core.workflow import build_workflow_graph
from src.models.enums import CriticDecision
from src.models.output import DocumentManifestEntry
from src.models.person import ClassifiedPerson, ExtractedPerson, ReconciledPerson, SourceReference
from src.models.workflow import CriticFeedback, ExtractorCriticFeedback, ExtractionIssueSimple
from src.services.document import DocumentInput, PageContent


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------


def make_source_ref(doc_id="test_doc_1", filename="test.pdf", page=1):
    return SourceReference(document_id=doc_id, filename=filename, page_number=page)


def make_document(doc_id="test_doc_1", filename="test.pdf") -> DocumentInput:
    return DocumentInput(
        document_id=doc_id,
        filename=filename,
        file_type="PDF",
        content="[PAGE 1]\nHans Müller, Geschäftsführer",
        pages=[PageContent(page_number=1, text="Hans Müller, Geschäftsführer")],
        page_count=1,
    )


def make_extracted_person(first="Hans", last="Müller", title="Managing Director", doc_name="test.pdf", page_number=1) -> ExtractedPerson:
    return ExtractedPerson(
        first_name=first,
        last_name=last,
        job_title=title,
        doc_name=doc_name,
        page_number=page_number,
    )


def make_reconciled_person(person_id="person_1", first="Hans", last="Müller", title="Managing Director") -> ReconciledPerson:
    return ReconciledPerson(
        person_id=person_id,
        first_name=first,
        last_name=last,
        first_name_normalized=first.lower(),
        last_name_normalized=last.lower(),
        job_title=title,
        source_references=[make_source_ref()],
    )


def make_classified_person(person_id="person_1", first="Hans", last="Müller", classification="CSM") -> ClassifiedPerson:
    return ClassifiedPerson(
        person_id=person_id,
        first_name=first,
        last_name=last,
        source_references=[make_source_ref()],
        classification=classification,
        reasoning="Test reasoning citing Criterion 1: Executive Management Role.",
        criteria_met=["Criterion 1: Executive Management Role"] if classification == "CSM" else [],
        criteria_not_met=[] if classification == "CSM" else ["Criterion 1-5: No CSM criteria met"],
    )


# ---------------------------------------------------------------------------
# CriticFeedback helpers
# ---------------------------------------------------------------------------


def pass_feedback(critic_name: str) -> CriticFeedback:
    return CriticFeedback(
        id=str(uuid4()),
        agent_execution_id=str(uuid4()),
        critic_agent_name=critic_name,
        decision=CriticDecision.PASS,
        suggested_corrections=None,
        created_at=datetime.now(),
    )


def fail_retry_feedback(critic_name: str, message: str = "Please retry") -> CriticFeedback:
    return CriticFeedback(
        id=str(uuid4()),
        agent_execution_id=str(uuid4()),
        critic_agent_name=critic_name,
        decision=CriticDecision.FAIL_RETRY,
        suggested_corrections=message,
        created_at=datetime.now(),
    )


def pass_extractor_feedback() -> ExtractorCriticFeedback:
    return ExtractorCriticFeedback(status="pass", issues=[], feedback="All records valid.")


def fail_extractor_feedback(message: str = "Invalid extraction.") -> ExtractorCriticFeedback:
    return ExtractorCriticFeedback(
        status="fail",
        issues=[ExtractionIssueSimple(
            first_name="?", last_name="?",
            issue_description=message,
            severity="error",
        )],
        feedback=message,
    )


def fail_max_feedback(critic_name: str) -> CriticFeedback:
    return CriticFeedback(
        id=str(uuid4()),
        agent_execution_id=str(uuid4()),
        critic_agent_name=critic_name,
        decision=CriticDecision.FAIL_MAX,
        suggested_corrections="Maximum retries exceeded.",
        created_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# Default mock agent functions
# ---------------------------------------------------------------------------


def default_extractor(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "extracted_persons": [make_extracted_person()]})


def default_critic_1_pass(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "extractor_critic_feedback": pass_extractor_feedback()})


def default_reconciler(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "reconciled_persons": [make_reconciled_person()], "duplicate_groups": []})


def default_critic_2_pass(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "last_critic_feedback": pass_feedback("critic_2")})


def default_classifier(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "classified_persons": [make_classified_person()]})


def default_critic_3_pass(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "last_critic_feedback": pass_feedback("critic_3")})


def default_formatter(state: WorkflowState) -> WorkflowState:
    classified = state.get("classified_persons", [])
    csm_list = [p for p in classified if p.classification == "CSM"]
    non_csm_list = [p for p in classified if p.classification == "NON_CSM"]
    return WorkflowState(
        **{
            **state,
            "document_manifest": [
                DocumentManifestEntry(filename="test.pdf", file_type="PDF", page_count=1, processing_status="processed")
            ],
            "csm_list": csm_list,
            "non_csm_list": non_csm_list,
            "status": "completed",
            "current_agent": "",
        }
    )


# ---------------------------------------------------------------------------
# Graph compilation helper
# ---------------------------------------------------------------------------


def build_compiled_workflow(
    extractor=None,
    critic_1=None,
    reconciler=None,
    critic_2=None,
    classifier=None,
    critic_3=None,
    formatter=None,
):
    """Build and compile a workflow with optional mock overrides.

    Unspecified agents use the default pass-through mocks.
    """
    workflows_config = load_workflows_config()
    functions = {
        "extractor": extractor or default_extractor,
        "critic_1": critic_1 or default_critic_1_pass,
        "reconciler": reconciler or default_reconciler,
        "critic_2": critic_2 or default_critic_2_pass,
        "classifier": classifier or default_classifier,
        "critic_3": critic_3 or default_critic_3_pass,
        "formatter": formatter or default_formatter,
    }
    graph = build_workflow_graph(functions, workflows_config)
    return graph.compile()
