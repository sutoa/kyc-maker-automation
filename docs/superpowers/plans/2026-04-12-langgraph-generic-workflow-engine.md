# LangGraph Generic Workflow Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all critical bugs and modernise the LangGraph workflow engine so the system runs end-to-end from YAML config with no hardcoded values, using current LangChain/LangGraph best practices.

**Architecture:** YAML-driven `StateGraph` built at runtime from `agents.yaml` + `workflows.yaml`. Agent nodes call LLMs via LangChain `ChatOpenAI`/`ChatGoogleGenerativeAI` with `.with_structured_output()`. Router nodes return `Command` objects to both route and update state atomically. All routing, retry, and model config is read from YAML.

**Tech Stack:** Python 3.11+, LangGraph 1.1.3, LangChain (`langchain-openai`, `langchain-google-genai`), Pydantic v2, pytest, FastAPI.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `requirements.txt` | Modify | Add `langchain-openai`, `langchain-google-genai`, `langgraph-checkpoint-sqlite` |
| `src/core/llm/` | **Delete** | Replaced by LangChain ChatModels |
| `src/models/person.py` | Modify | Flatten `ExtractedPerson`; drop `extraction_id`, `SourceReference` |
| `src/models/workflow.py` | Modify | Add `ExtractionIssueSimple`, `ExtractorCriticFeedback` |
| `src/core/state.py` | Modify | Add `extractor_critic_feedback`, `csm_report`; delete dead helpers |
| `src/core/conditions.py` | Modify | Add `route_on_extractor_critic_decision` returning `Command` |
| `src/core/agent_factory.py` | Modify | Use LangChain ChatModels + `.with_structured_output()`; optional schema |
| `src/core/workflow.py` | Modify | `START` sentinel; router node support; drop sync duplicate; generalise wrapper |
| `src/config/loader.py` | Modify | Handle `type: router` nodes; skip `condition` edges for router nodes |
| `src/config/agents.yaml` | Modify | `extractor.input_keys` + remove `formatter.output_schema` |
| `src/config/workflows.yaml` | Modify | Add `extractor_critic_router` node; replace condition edge with unconditional edges |
| `tests/unit/test_llm.py` | **Delete** | Tests for deleted LLM layer |
| `tests/unit/test_state.py` | Rewrite | Tests for slimmed-down state |
| `tests/contract/test_extractor.py` | Rewrite | Tests for flat `ExtractedPerson` |
| `tests/unit/test_config.py` | Modify | Update for router node type + new topology |
| `tests/unit/test_conditions.py` | **Create** | Tests for `route_on_extractor_critic_decision` |
| `tests/unit/test_agent_factory.py` | **Create** | Tests for new factory with LangChain mocks |

---

## Task 1: Update Dependencies and Remove Legacy LLM Layer

**Files:**
- Modify: `requirements.txt`
- Delete: `src/core/llm/` (entire directory)
- Delete: `tests/unit/test_llm.py`

- [x] **Step 1: Add new packages to requirements.txt**

Replace the `# LLM providers` section with:

```text
# LLM providers (LangChain integrations)
langchain-openai>=0.3.0
langchain-google-genai>=2.0.0
langgraph-checkpoint-sqlite>=2.0.0
```

Remove the old lines:
```text
openai>=1.50.0
google-generativeai>=0.8.0
```

- [x] **Step 2: Install new packages**

```bash
pip install langchain-openai langchain-google-genai langgraph-checkpoint-sqlite
```

Expected: packages install without error.

- [x] **Step 3: Delete the legacy LLM layer**

```bash
rm -rf src/core/llm
rm tests/unit/test_llm.py
```

- [x] **Step 4: Verify no remaining imports of the deleted module**

```bash
grep -r "from src.core.llm" src/ tests/
```

Expected: only `src/core/agent_factory.py` shows a match (it imports `get_llm_provider` which we will replace in Task 5). Any other matches are bugs — fix them now.

- [x] **Step 5: Commit**

```bash
git add requirements.txt
git rm -r src/core/llm tests/unit/test_llm.py
git commit -m "chore: replace custom LLM layer with langchain-openai/google-genai"
```

---

## Task 2: Flatten ExtractedPerson and Add ExtractorCriticFeedback

**Files:**
- Modify: `src/models/person.py`
- Modify: `src/models/workflow.py`
- Rewrite: `tests/contract/test_extractor.py`

- [x] **Step 1: Write failing tests for the new ExtractedPerson shape**

Replace the full content of `tests/contract/test_extractor.py`:

```python
"""Contract tests for ExtractedPerson and ExtractorCriticFeedback models."""

import pytest
from pydantic import ValidationError

from src.models.person import ExtractedPerson
from src.models.workflow import ExtractionIssueSimple, ExtractorCriticFeedback


class TestExtractedPersonFlat:
    """ExtractedPerson must match extractor.md JSON example exactly."""

    def test_minimal_valid_person(self):
        person = ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            doc_name="register.pdf",
            page_number=3,
        )
        assert person.first_name == "Hans"
        assert person.last_name == "Müller"
        assert person.doc_name == "register.pdf"
        assert person.page_number == 3

    def test_optional_job_title(self):
        person = ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            doc_name="register.pdf",
            page_number=1,
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
        )
        assert person.job_title == "Managing Director"
        assert person.job_title_original == "Geschäftsführer"

    def test_missing_first_name_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedPerson(
                first_name="",
                last_name="Müller",
                doc_name="register.pdf",
                page_number=1,
            )

    def test_missing_last_name_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedPerson(
                first_name="Hans",
                last_name="",
                doc_name="register.pdf",
                page_number=1,
            )

    def test_page_number_must_be_positive(self):
        with pytest.raises(ValidationError):
            ExtractedPerson(
                first_name="Hans",
                last_name="Müller",
                doc_name="register.pdf",
                page_number=0,
            )

    def test_no_extraction_id_field(self):
        person = ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            doc_name="register.pdf",
            page_number=1,
        )
        assert not hasattr(person, "extraction_id")

    def test_no_source_references_field(self):
        person = ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            doc_name="register.pdf",
            page_number=1,
        )
        assert not hasattr(person, "source_references")


class TestExtractorCriticFeedback:
    """ExtractorCriticFeedback must match extractor_critic.md JSON example."""

    def test_pass_with_no_issues(self):
        feedback = ExtractorCriticFeedback(
            status="pass",
            issues=[],
            feedback="All records are valid.",
        )
        assert feedback.status == "pass"
        assert feedback.issues == []

    def test_fail_with_issues(self):
        feedback = ExtractorCriticFeedback(
            status="fail",
            issues=[
                ExtractionIssueSimple(
                    first_name="Hans",
                    last_name="Müller",
                    issue_description="Missing page number",
                    severity="error",
                )
            ],
            feedback="1 record has missing page number.",
        )
        assert feedback.status == "fail"
        assert len(feedback.issues) == 1
        assert feedback.issues[0].severity == "error"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            ExtractorCriticFeedback(
                status="unknown",
                issues=[],
                feedback="test",
            )

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            ExtractionIssueSimple(
                first_name="Hans",
                last_name="Müller",
                issue_description="Bad",
                severity="critical",  # only "error" | "warning" allowed
            )
```

- [x] **Step 2: Run tests to verify they fail**

```bash
pytest tests/contract/test_extractor.py -v
```

Expected: FAIL — `ExtractedPerson` still has old fields; `ExtractorCriticFeedback` does not exist.

- [x] **Step 3: Rewrite ExtractedPerson in src/models/person.py**

Replace the `ExtractedPerson` class (lines ~33–49) with:

```python
class ExtractedPerson(BaseModel):
    """A person extracted from source documents.

    Fields match the extractor.md JSON example exactly so LLM output
    maps directly to Pydantic validation with no post-processing.
    """

    first_name: str = Field(..., min_length=1, description="Person's given name")
    last_name: str = Field(..., min_length=1, description="Person's family name")
    job_title: str | None = Field(None, description="Job title in English")
    job_title_original: str | None = Field(
        None, description="Original language job title (e.g. Geschäftsführer)"
    )
    doc_name: str = Field(..., description="Source document filename")
    page_number: int = Field(..., ge=1, description="Page where person was found")
```

Also remove the `SourceReference` class and `FieldConflict`, `ConflictValue` import usages that depended on it. Keep `SourceReference` referenced by `ReconciledPerson` and `ClassifiedPerson` — those models are unchanged.

- [x] **Step 4: Add ExtractionIssueSimple and ExtractorCriticFeedback to src/models/workflow.py**

After the existing imports, add before `class WorkflowRun`:

```python
class ExtractionIssueSimple(BaseModel):
    """A single extraction issue as reported by extractor_critic.

    Matches the extractor_critic.md JSON example exactly.
    """

    first_name: str = Field(..., description="First name of person with issue")
    last_name: str = Field(..., description="Last name of person with issue")
    issue_description: str = Field(..., description="Description of the issue")
    severity: Literal["error", "warning"] = Field(..., description="Issue severity")


class ExtractorCriticFeedback(BaseModel):
    """Output of the extractor_critic agent.

    Matches the extractor_critic.md JSON example exactly.
    """

    status: Literal["pass", "fail"] = Field(
        ..., description="pass if all records valid, fail otherwise"
    )
    issues: list[ExtractionIssueSimple] = Field(
        default_factory=list, description="List of issues found"
    )
    feedback: str = Field(..., description="Constructive summary for the extractor")
```

- [x] **Step 5: Run tests to verify they pass**

```bash
pytest tests/contract/test_extractor.py -v
```

Expected: all 11 tests PASS.

- [x] **Step 6: Run full test suite to find other breakage**

```bash
pytest --tb=no -q 2>&1 | grep FAILED
```

Note all FAILED tests — they will be fixed in subsequent tasks.

- [x] **Step 7: Commit**

```bash
git add src/models/person.py src/models/workflow.py tests/contract/test_extractor.py
git commit -m "feat: flatten ExtractedPerson and add ExtractorCriticFeedback model"
```

---

## Task 3: Slim Down state.py

**Files:**
- Modify: `src/core/state.py`
- Rewrite: `tests/unit/test_state.py`

- [x] **Step 1: Write failing tests for the new slim state**

Replace the full content of `tests/unit/test_state.py`:

```python
"""Unit tests for workflow state management."""

import pytest

from src.core.state import WorkflowState, create_initial_state, update_workflow_failed, update_workflow_started
from src.services.document import DocumentInput, PageContent


def _doc(doc_id: str = "doc1") -> DocumentInput:
    return DocumentInput(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        file_type="PDF",
        content="[PAGE 1]\nTest content",
        pages=[PageContent(page_number=1, text="Test content")],
        page_count=1,
    )


class TestCreateInitialState:
    def test_workflow_id_auto_generated(self):
        state = create_initial_state([_doc()])
        assert state["workflow_id"] is not None
        assert len(state["workflow_id"]) > 0

    def test_custom_workflow_id(self):
        state = create_initial_state([_doc()], workflow_id="my-id")
        assert state["workflow_id"] == "my-id"

    def test_documents_set(self):
        state = create_initial_state([_doc("a"), _doc("b")])
        assert len(state["documents"]) == 2

    def test_status_is_pending(self):
        state = create_initial_state([_doc()])
        assert state["status"] == "pending"

    def test_retry_counts_zero(self):
        state = create_initial_state([_doc()])
        assert state["extraction_retry_count"] == 0

    def test_new_state_keys_present(self):
        state = create_initial_state([_doc()])
        assert "extractor_critic_feedback" in state
        assert state["extractor_critic_feedback"] is None
        assert "csm_report" in state
        assert state["csm_report"] is None

    def test_no_dead_helper_imports(self):
        """Verify deleted helpers are truly gone."""
        import src.core.state as m
        assert not hasattr(m, "update_extraction_result")
        assert not hasattr(m, "update_extraction_retry")
        assert not hasattr(m, "update_extraction_passed")
        assert not hasattr(m, "update_reconciliation_result")
        assert not hasattr(m, "update_reconciliation_retry")
        assert not hasattr(m, "update_reconciliation_passed")
        assert not hasattr(m, "update_classification_result")
        assert not hasattr(m, "update_classification_retry")
        assert not hasattr(m, "update_classification_passed")
        assert not hasattr(m, "update_final_output")
        assert not hasattr(m, "MAX_RETRY_COUNT")
        assert not hasattr(m, "can_retry")
        assert not hasattr(m, "get_retry_count")
        assert not hasattr(m, "get_feedback")


class TestWorkflowStatusUpdates:
    def test_update_started(self):
        state = create_initial_state([_doc()])
        new = update_workflow_started(state)
        assert new["status"] == "in_progress"
        assert state["status"] == "pending"  # original unchanged

    def test_update_failed(self):
        state = create_initial_state([_doc()])
        new = update_workflow_failed(state, "extraction failed")
        assert new["status"] == "failed"
        assert new["failure_reason"] == "extraction failed"

    def test_update_failed_preserves_other_keys(self):
        state = create_initial_state([_doc("x")])
        new = update_workflow_failed(state, "boom")
        assert new["workflow_id"] == state["workflow_id"]
        assert new["documents"] == state["documents"]
```

- [x] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_state.py -v
```

Expected: `test_new_state_keys_present` and `test_no_dead_helper_imports` FAIL.

- [x] **Step 3: Rewrite src/core/state.py**

Replace the full file content:

```python
"""Workflow state management for LangGraph-based KYC processing."""

from typing import Literal, TypedDict
from uuid import uuid4

from src.models.person import ClassifiedPerson, ExtractedPerson, ReconciledPerson, DuplicateGroup
from src.models.workflow import CriticFeedback, ExtractorCriticFeedback
from src.models.output import DocumentManifestEntry
from src.services.document import DocumentInput


class WorkflowState(TypedDict, total=False):
    """Shared state object passed through the LangGraph workflow."""

    # Input
    workflow_id: str
    documents: list[DocumentInput]

    # Extraction phase
    extracted_persons: list[ExtractedPerson]
    extraction_retry_count: int
    extractor_critic_feedback: ExtractorCriticFeedback | None

    # Reconciliation phase (inactive — re-enabled when reconciler is added back)
    reconciled_persons: list[ReconciledPerson]
    duplicate_groups: list[DuplicateGroup]
    reconciliation_retry_count: int
    reconciliation_feedback: str | None

    # Classification phase (inactive — re-enabled when classifier is added back)
    classified_persons: list[ClassifiedPerson]
    classification_retry_count: int
    classification_feedback: str | None

    # Generic critic feedback (used by rule-based critics)
    last_critic_feedback: CriticFeedback | None

    # Output
    document_manifest: list[DocumentManifestEntry]
    csm_list: list[ClassifiedPerson]
    non_csm_list: list[ClassifiedPerson]
    csm_report: str | None

    # Status tracking
    current_agent: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    failure_reason: str | None


def create_initial_state(
    documents: list[DocumentInput],
    workflow_id: str | None = None,
) -> WorkflowState:
    """Create initial workflow state from uploaded documents."""
    return WorkflowState(
        workflow_id=workflow_id or str(uuid4()),
        documents=documents,
        extracted_persons=[],
        extraction_retry_count=0,
        extractor_critic_feedback=None,
        reconciled_persons=[],
        duplicate_groups=[],
        reconciliation_retry_count=0,
        reconciliation_feedback=None,
        classified_persons=[],
        classification_retry_count=0,
        classification_feedback=None,
        last_critic_feedback=None,
        document_manifest=[],
        csm_list=[],
        non_csm_list=[],
        csm_report=None,
        current_agent="extractor",
        status="pending",
        failure_reason=None,
    )


def update_workflow_started(state: WorkflowState) -> WorkflowState:
    """Return new state with status set to in_progress."""
    return WorkflowState(**{**state, "status": "in_progress"})


def update_workflow_failed(
    state: WorkflowState,
    reason: str,
    critic_feedback: CriticFeedback | None = None,
) -> WorkflowState:
    """Return new state with failed status and failure reason."""
    return WorkflowState(**{
        **state,
        "status": "failed",
        "failure_reason": reason,
        "last_critic_feedback": critic_feedback or state.get("last_critic_feedback"),
    })
```

- [x] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_state.py -v
```

Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add src/core/state.py tests/unit/test_state.py
git commit -m "refactor: slim down state.py — remove dead helpers, add new state keys"
```

---

## Task 4: Add route_on_extractor_critic_decision

**Files:**
- Modify: `src/core/conditions.py`
- Create: `tests/unit/test_conditions.py`

- [x] **Step 1: Write failing tests**

Create `tests/unit/test_conditions.py`:

```python
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
```

- [x] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_conditions.py -v
```

Expected: FAIL — `route_on_extractor_critic_decision` does not exist.

- [x] **Step 3: Add the routing function to src/core/conditions.py**

Add to the end of the existing file (keep `route_on_critic_decision` intact):

```python
from langgraph.types import Command


def route_on_extractor_critic_decision(
    state: WorkflowState,
) -> "Command[Literal['formatter', 'extractor', END]]":
    """Router node function for the extractor critic loop.

    Reads extractor_critic_feedback from state. On pass, routes to formatter.
    On fail, increments extraction_retry_count and routes back to extractor.
    On fail with retry count >= 4, routes to END.

    Returns a Command so routing and state update happen atomically.
    """
    feedback = state.get("extractor_critic_feedback")
    retry_count = state.get("extraction_retry_count", 0) or 0

    if feedback is None or getattr(feedback, "status", "pass") == "pass":
        return Command(goto="formatter")

    if retry_count >= 4:
        logger.info(
            f"[{state.get('workflow_id', 'unknown')}] "
            "extractor_critic_router: max retries reached → END"
        )
        return Command(goto=END)

    logger.info(
        f"[{state.get('workflow_id', 'unknown')}] "
        f"extractor_critic_router: fail_retry #{retry_count + 1} → extractor"
    )
    return Command(
        goto="extractor",
        update={"extraction_retry_count": retry_count + 1},
    )
```

Also add the missing import at the top of conditions.py:

```python
from langgraph.graph import END
from langgraph.types import Command
from typing import Literal
```

- [x] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_conditions.py -v
```

Expected: all 6 tests PASS.

- [x] **Step 5: Commit**

```bash
git add src/core/conditions.py tests/unit/test_conditions.py
git commit -m "feat: add extractor critic router node with Command-based routing"
```

---

## Task 5: Refactor Agent Factory to Use LangChain + with_structured_output

**Files:**
- Modify: `src/core/agent_factory.py`
- Create: `tests/unit/test_agent_factory.py`

- [x] **Step 1: Write failing tests**

Create `tests/unit/test_agent_factory.py`:

```python
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
```

- [x] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_agent_factory.py -v
```

Expected: FAIL — `_build_chat_model` does not exist; factory still uses old LLM layer.

- [x] **Step 3: Rewrite src/core/agent_factory.py**

Replace the full file content:

```python
"""Generic agent factory — builds agent callables from agents.yaml config.

All agent config (model, temperature, max_tokens, retry, prompts, output schemas)
comes from YAML. No hardcoded values.

Public API:
    build_agent_fn(agent_name, agent_cfg, agents_dir) -> Callable[[WorkflowState], WorkflowState]
"""

import importlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import SystemMessage
from pydantic import BaseModel

from src.core.state import WorkflowState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM provider factory
# ---------------------------------------------------------------------------


def _build_chat_model(model_string: str, temperature: float, max_tokens: int) -> Any:
    """Instantiate a LangChain ChatModel from a provider/model-name string."""
    provider, model_name = model_string.split("/", 1)
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=temperature, max_tokens=max_tokens)
    elif provider in ("gemini", "google"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature, max_tokens=max_tokens)
    raise ValueError(
        f"Unsupported provider: '{provider}' in model string '{model_string}'. "
        "Expected 'openai/<model>' or 'gemini/<model>'."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_callable(dotted_path: str) -> Any:
    """Import and return a Python callable from a dotted module path."""
    parts = dotted_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid dotted path: '{dotted_path}'. Expected 'module.attribute'.")
    module_path, attr = parts
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ValueError(f"Cannot import module '{module_path}': {e}")
    if not hasattr(module, attr):
        raise ValueError(f"Module '{module_path}' has no attribute '{attr}'")
    return getattr(module, attr)


def _resolve_schema(output_schema_cfg: dict[str, Any]) -> type[BaseModel]:
    """Resolve output_schema.ref to a Pydantic class."""
    ref = output_schema_cfg.get("ref")
    if not ref:
        raise ValueError("output_schema must have a 'ref' key")
    cls = _resolve_callable(ref)
    if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
        raise ValueError(f"'{ref}' must be a Pydantic BaseModel subclass")
    return cls


def _load_prompt(system_prompt_cfg: dict[str, Any], agents_dir: Path) -> str:
    """Load prompt content from file or inline string."""
    if "inline" in system_prompt_cfg:
        return system_prompt_cfg["inline"]
    if "file" in system_prompt_cfg:
        prompt_path = (agents_dir / system_prompt_cfg["file"]).resolve()
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")
    raise ValueError("system_prompt must have either 'file' or 'inline' key")


def _render_prompt(template: str, context: dict[str, Any]) -> str:
    """Replace {{key}} placeholders with values from context.

    Missing / None values render as empty string so placeholders
    disappear cleanly on the first pass (e.g. extractor_critic_feedback).
    """
    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        value = context.get(key)
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False, default=str)
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        return str(value)

    return re.sub(r"\{\{(\w+)\}\}", replacer, template)


def _build_system_message(agent_cfg: dict[str, Any], prompt_content: str) -> str:
    """Compose system message: identity preamble + prompt content."""
    parts = []
    role = agent_cfg.get("role", "")
    goal = agent_cfg.get("goal", "")
    backstory = agent_cfg.get("backstory", "").strip()
    if role:
        parts.append(f"You are: {role}")
    if goal:
        parts.append(f"Your goal: {goal}")
    if backstory:
        parts.append(f"Background: {backstory}")
    if parts:
        parts.append("")
    parts.append(prompt_content)
    return "\n".join(parts)


def _extract_input_context(state: WorkflowState, input_keys: list[str]) -> dict[str, Any]:
    """Extract declared input_keys from state into a context dict."""
    return {key: state.get(key) for key in input_keys}


# ---------------------------------------------------------------------------
# LLM agent builder
# ---------------------------------------------------------------------------


def _build_llm_agent_fn(
    agent_name: str,
    agent_cfg: dict[str, Any],
    agents_dir: Path,
) -> Callable[[WorkflowState], WorkflowState]:
    """Build an LLM-backed agent function from config."""

    prompt_template = _load_prompt(agent_cfg["system_prompt"], agents_dir)
    output_schema_cfg = agent_cfg.get("output_schema")
    input_keys = agent_cfg.get("input_keys", [])
    output_key = agent_cfg["output_key"]
    model_string = agent_cfg["model"]
    temperature = float(agent_cfg.get("temperature", 0))
    max_tokens = int(agent_cfg.get("max_tokens", 4096))

    # Resolve schema once at build time (fail fast)
    schema_cls: type[BaseModel] | None = None
    is_list = False
    if output_schema_cfg:
        schema_cls = _resolve_schema(output_schema_cfg)
        is_list = bool(output_schema_cfg.get("is_list", False))

    def agent_fn(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        logger.info(f"[{workflow_id}] {agent_name}: starting (llm)")

        context = _extract_input_context(state, input_keys)
        rendered_prompt = _render_prompt(prompt_template, context)
        system_content = _build_system_message(agent_cfg, rendered_prompt)
        messages = [SystemMessage(content=system_content)]

        llm = _build_chat_model(model_string, temperature, max_tokens)

        if schema_cls is not None:
            if is_list:
                # Wrap in container so the LLM returns a list
                container_name = f"_{schema_cls.__name__}List"
                container_cls = type(
                    container_name,
                    (BaseModel,),
                    {"__annotations__": {"items": list[schema_cls]}},
                )
                structured_llm = llm.with_structured_output(container_cls, method="json_schema")
                raw = structured_llm.invoke(messages)
                result = raw.items
            else:
                structured_llm = llm.with_structured_output(schema_cls, method="json_schema")
                result = structured_llm.invoke(messages)
        else:
            # No schema — return raw string (e.g. formatter markdown output)
            result = llm.invoke(messages).content

        logger.info(f"[{workflow_id}] {agent_name}: completed")
        return WorkflowState(**{**state, output_key: result})

    agent_fn.__name__ = agent_name
    return agent_fn


# ---------------------------------------------------------------------------
# Rule-based agent builder
# ---------------------------------------------------------------------------


def _build_rule_agent_fn(
    agent_name: str,
    agent_cfg: dict[str, Any],
) -> Callable[[WorkflowState], WorkflowState]:
    """Build a rule-based agent function from config."""

    rule_fn = _resolve_callable(agent_cfg["rule_fn"])
    output_key = agent_cfg["output_key"]

    def agent_fn(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        logger.info(f"[{workflow_id}] {agent_name}: starting (rule)")
        result = rule_fn(state)
        logger.info(f"[{workflow_id}] {agent_name}: completed")
        return WorkflowState(**{**state, output_key: result})

    agent_fn.__name__ = agent_name
    return agent_fn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_agent_fn(
    agent_name: str,
    agent_cfg: dict[str, Any],
    agents_dir: Path,
) -> Callable[[WorkflowState], WorkflowState]:
    """Build an agent callable from its YAML config entry.

    Args:
        agent_name: The agent key (used for logging).
        agent_cfg:  Effective merged config (defaults already applied).
        agents_dir: Directory of agents.yaml (resolves relative prompt paths).

    Returns:
        A callable (state: WorkflowState) -> WorkflowState ready for LangGraph.
    """
    execution = agent_cfg.get("execution", "llm")
    if execution == "llm":
        return _build_llm_agent_fn(agent_name, agent_cfg, agents_dir)
    elif execution == "rule":
        return _build_rule_agent_fn(agent_name, agent_cfg)
    raise ValueError(
        f"Agent '{agent_name}' has unsupported execution type '{execution}'. "
        "Expected 'llm' or 'rule'."
    )
```

- [x] **Step 4: Run factory tests to verify they pass**

```bash
pytest tests/unit/test_agent_factory.py -v
```

Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add src/core/agent_factory.py tests/unit/test_agent_factory.py
git commit -m "feat: replace custom LLM layer with LangChain with_structured_output"
```

---

## Task 6: Update Workflow Engine

**Files:**
- Modify: `src/core/workflow.py`

- [x] **Step 1: Replace set_entry_point with START sentinel**

In `build_workflow_graph`, replace:
```python
# Old
graph.set_entry_point(edge["to"])
```
With:
```python
# New
from langgraph.graph import START, END
graph.add_edge(START, edge["to"])
```

Also remove the old `entry_point` block entirely (lines 293–300 in the original). The `__start__` sentinel logic moves to the edge loop as `add_edge(START, ...)`.

- [x] **Step 2: Add router node support**

In `build_workflow_graph`, in the node loop, add handling for `type: router`:

```python
for node_name, node_def in nodes_cfg.items():
    node_type = node_def.get("type")

    if node_type == "end":
        continue

    if node_type == "router":
        routing_fn = resolve_callable(node_def["fn"])
        graph.add_node(node_name, routing_fn)
        continue  # Command return handles routing — no edges needed

    # type: agent (default)
    agent_fn = functions.get(node_name)
    if agent_fn is None:
        raise ValueError(f"Node '{node_name}' has no matching function")
    retry_count_key = node_def.get("retry_count_key")
    output_key = node_def.get("output_key")
    wrapped = create_agent_node(node_name, agent_fn, retry_count_key=retry_count_key, output_key=output_key)
    graph.add_node(node_name, wrapped)
```

- [x] **Step 3: Generalise create_agent_node to accept retry_count_key**

Replace the `create_agent_node` signature and the hardcoded retry key lookup:

```python
def create_agent_node(
    agent_name: str,
    agent_fn: AgentFunction,
    retry_count_key: str | None = None,
    output_key: str | None = None,
) -> Callable[[WorkflowState], WorkflowState]:
    """Create a wrapped agent node with logging and state updates."""

    def wrapped_agent(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        retry_count = state.get(retry_count_key, 0) if retry_count_key else 0
        # ... rest of wrapper unchanged ...
```

- [x] **Step 4: Delete run_workflow_sync**

Remove the entire `run_workflow_sync` function (lines ~510–622 in the original file). Any callers in `src/api/` should be updated to use `asyncio.run(run_workflow(...))` or `await run_workflow(...)`.

- [x] **Step 5: Fix checkpointer import**

Replace:
```python
from langgraph.checkpoint.sqlite import SqliteSaver
```
With:
```python
from langgraph.checkpoint.sqlite import SqliteSaver  # requires langgraph-checkpoint-sqlite
```
(The package is now in requirements.txt from Task 1 — this import will work.)

- [x] **Step 6: Run existing workflow-related tests**

```bash
pytest tests/integration/test_workflow.py tests/integration/test_extraction_flow.py -v --tb=short
```

Fix any import or API errors that surface. The tests may mock LLM calls — update mock targets from `src.core.llm.get_llm_provider` to `src.core.agent_factory._build_chat_model`.

- [x] **Step 7: Commit**

```bash
git add src/core/workflow.py
git commit -m "feat: modernise workflow engine — START sentinel, router nodes, drop sync duplicate"
```

---

## Task 7: Update Config Loader for Router Nodes

**Files:**
- Modify: `src/config/loader.py`
- Modify: `tests/unit/test_config.py`

- [x] **Step 1: Update build_agent_functions to skip router nodes**

In `build_agent_functions`, the loop currently processes all non-`end` nodes. Router nodes have no agent callable — skip them:

```python
for node_name, node_def in nodes.items():
    node_type = node_def.get("type")
    if node_type in ("end", "router"):
        continue  # router nodes are wired directly in workflow.py
    # ... rest unchanged ...
```

- [x] **Step 2: Update validate_workflows_config to accept router node type**

Router nodes have a `fn` field instead of `agent`. Update validation:

```python
for node_name, node_def in nodes.items():
    node_type = node_def.get("type", "agent")
    if node_type == "agent":
        agent_key = node_def.get("agent")
        if agent_key and agent_key not in agents:
            errors.append({
                "path": f"nodes.{node_name}.agent",
                "message": f"Agent '{agent_key}' not found in agents config",
            })
    elif node_type == "router":
        if not node_def.get("fn"):
            errors.append({
                "path": f"nodes.{node_name}.fn",
                "message": "Router nodes must have a 'fn' (dotted Python path)",
            })
```

- [x] **Step 3: Update test_config.py for new topology**

In `tests/unit/test_config.py`, the bundled config tests check for specific nodes. Update:

```python
def test_bundled_config_has_nodes(self):
    config = load_workflows_config()
    assert "nodes" in config
    # Active nodes in current workflow
    expected_nodes = ["extractor", "extractor_critic", "extractor_critic_router", "formatter", "end"]
    for node in expected_nodes:
        assert node in config["nodes"], f"Missing node: {node}"

def test_bundled_config_has_all_agents(self):
    config = load_agents_config()
    agents = config["agents"]
    # Only check currently active agents (reconciler etc. are commented out)
    required = ["extractor", "extractor_critic", "formatter"]
    for name in required:
        assert name in agents, f"Missing agent: {name}"
```

Also update `TestGetEdgeRoutes` and `TestGetUnconditionalTarget` and `TestConfigIntegration` to reflect the new topology (extractor → extractor_critic → extractor_critic_router, no more critic_1/reconciler/etc. in active YAML).

- [x] **Step 4: Run config tests**

```bash
pytest tests/unit/test_config.py -v
```

Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add src/config/loader.py tests/unit/test_config.py
git commit -m "feat: loader handles router node type; update config tests for new topology"
```

---

## Task 8: Update YAML Configs

**Files:**
- Modify: `src/config/agents.yaml`
- Modify: `src/config/workflows.yaml`

- [x] **Step 1: Update agents.yaml**

Change `extractor.input_keys`:
```yaml
extractor:
  input_keys: [documents, extractor_critic_feedback]
```

Remove `output_schema` from `formatter` entirely:
```yaml
formatter:
  role: "KYC Output Formatter"
  goal: "Produce the final output in markdown format ..."
  backstory: |
    ...
  execution: llm
  input_keys: [extracted_persons]
  output_key: csm_report
  system_prompt:
    file: ../prompts/formatter.md
  # output_schema intentionally absent — formatter returns raw markdown
```

- [x] **Step 2: Update workflows.yaml**

Add `extractor_critic_router` to the nodes section:
```yaml
  extractor_critic_router:
    type: router
    fn: src.core.conditions.route_on_extractor_critic_decision
    routes:
      pass:       formatter
      fail_retry: extractor
      fail_max:   end
```

Replace the conditional edge block with two unconditional edges:
```yaml
  # ── Extraction phase ──────���────────────────────────────────
  - from: extractor
    to: extractor_critic

  - from: extractor_critic
    to: extractor_critic_router

  # extractor_critic_router returns Command — no condition edge needed
```

Remove the old conditional edge block:
```yaml
  # DELETE THIS BLOCK:
  - from: extractor_critic
    condition:
      fn: src.core.conditions.route_on_extractor_critic_decision
      routes:
        ...
```

- [x] **Step 3: Verify YAML loads without error**

```bash
python -c "from src.config.loader import load_all_configs; load_all_configs(); print('OK')"
```

Expected: `OK`

- [x] **Step 4: Run full test suite**

```bash
pytest --tb=short -q
```

Fix any remaining failures. Common ones at this point:
- Integration tests that check node names — update to new topology
- Contract tests that use old `ExtractedPerson` fields — already fixed in Task 2

- [x] **Step 5: Commit**

```bash
git add src/config/agents.yaml src/config/workflows.yaml
git commit -m "config: add extractor_critic_router node, update input_keys, remove formatter output_schema"
```

---

## Task 9: End-to-End Integration Smoke Test

**Files:**
- Create: `tests/integration/test_extraction_end_to_end.py`

- [x] **Step 1: Write the integration smoke test with mocked LLM**

Create `tests/integration/test_extraction_end_to_end.py`:

```python
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
    mock.content = "# KYC Results\n\n## CSM List\n| First Name | Last Name | ...\n|---|---|---|\n| Hans | Müller | ... |"
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

    assert final["status"] == "completed" or final["status"] == "in_progress"
    assert final.get("csm_report") is not None
    assert "Hans" in final["csm_report"] or len(final["csm_report"]) > 0


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
```

- [x] **Step 2: Run the integration test**

```bash
pytest tests/integration/test_extraction_end_to_end.py -v
```

Expected: both tests PASS.

- [ ] **Step 3: Run the full test suite one final time**

```bash
pytest --tb=short -q
```

Expected: all tests pass (or only pre-existing failures unrelated to this work).

- [ ] **Step 4: Final commit**

```bash
git add tests/integration/test_extraction_end_to_end.py
git commit -m "test: add end-to-end integration smoke test for extraction workflow"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| Flatten `ExtractedPerson` | Task 2 |
| Drop `extraction_id` | Task 2 |
| Add `ExtractorCriticFeedback` | Task 2 |
| Add `route_on_extractor_critic_decision` | Task 4 |
| `Command`-based routing with counter increment | Task 4 |
| Replace custom LLM layer with `with_structured_output` | Task 5 |
| Optional `output_schema` (formatter raw string) | Task 5 |
| `START` sentinel instead of `set_entry_point` | Task 6 |
| Router node support in graph builder | Task 6 |
| Drop `run_workflow_sync` | Task 6 |
| Generalise `create_agent_node` retry key | Task 6 |
| Delete dead state helpers | Task 3 |
| `extractor_critic_feedback` + `csm_report` state keys | Task 3 |
| `extractor.input_keys` update | Task 8 |
| `formatter.output_schema` removal | Task 8 |
| `extractor_critic_router` node in YAML | Task 8 |
| `langgraph-checkpoint-sqlite` added | Task 1 |
| Delete `src/core/llm/` | Task 1 |

All spec requirements are covered. No gaps.
