"""Extractor agent for KYC document processing.

This agent extracts person information from KYC documents using an LLM.
It handles German business documents with proper terminology translation
and maintains source references for audit trails.
"""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.state import WorkflowState, get_feedback, update_extraction_result
from src.models.person import ExtractedPerson, SourceReference
from src.services.document import DocumentInput

logger = logging.getLogger(__name__)

# Path to the extractor prompt template
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extractor.md"


class ExtractorInput(BaseModel):
    """Input contract for the extractor agent."""

    documents: list[DocumentInput] = Field(
        ..., description="Documents to extract persons from"
    )
    retry_feedback: str | None = Field(
        None, description="Feedback from critic if retrying"
    )


class ExtractorOutput(BaseModel):
    """Output contract for the extractor agent."""

    extracted_persons: list[ExtractedPerson] = Field(
        ..., description="List of extracted persons"
    )


def load_prompt_template() -> str:
    """Load the extractor prompt template.

    Returns:
        The prompt template as a string.

    Raises:
        FileNotFoundError: If prompt file not found.
    """
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Extractor prompt not found: {PROMPT_PATH}")

    return PROMPT_PATH.read_text(encoding="utf-8")


def render_prompt(
    documents: list[DocumentInput],
    retry_feedback: str | None = None,
) -> str:
    """Render the extractor prompt with document content.

    Args:
        documents: Documents to include in the prompt.
        retry_feedback: Optional feedback from previous extraction attempt.

    Returns:
        Rendered prompt ready for LLM.
    """
    import json

    template = load_prompt_template()

    # Build documents list for JSON substitution
    docs_list = [
        {
            "document_id": doc.document_id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "page_count": doc.page_count,
            "content": doc.content,
        }
        for doc in documents
    ]

    # Substitute {{documents}} and {{extraction_feedback}} placeholders
    prompt = template.replace("{{documents}}", json.dumps(docs_list, ensure_ascii=False, indent=2))
    prompt = prompt.replace("{{extraction_feedback}}", retry_feedback or "")

    return prompt


def parse_llm_response(
    response_text: str,
    documents: list[DocumentInput],
) -> list[ExtractedPerson]:
    """Parse LLM response into ExtractedPerson objects.

    Args:
        response_text: Raw text response from LLM.
        documents: Original documents for reference validation.

    Returns:
        List of ExtractedPerson objects.

    Raises:
        ValueError: If response cannot be parsed.
    """
    # Try to extract JSON from the response
    # The LLM might return markdown code blocks
    json_text = response_text

    # Remove markdown code blocks if present
    if "```json" in json_text:
        start = json_text.find("```json") + 7
        end = json_text.find("```", start)
        json_text = json_text[start:end].strip()
    elif "```" in json_text:
        start = json_text.find("```") + 3
        end = json_text.find("```", start)
        json_text = json_text[start:end].strip()

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        logger.debug(f"Response text: {response_text[:500]}...")
        raise ValueError(f"Invalid JSON in LLM response: {e}")

    # Handle both array and object with extracted_persons key
    if isinstance(data, dict):
        persons_data = data.get("extracted_persons", data.get("persons", []))
    elif isinstance(data, list):
        persons_data = data
    else:
        raise ValueError(f"Unexpected response format: {type(data)}")

    # Build document lookup for validation
    doc_lookup = {doc.document_id: doc for doc in documents}

    # Parse each person
    extracted_persons = []
    for i, person_data in enumerate(persons_data):
        try:
            # Ensure extraction_id exists
            if "extraction_id" not in person_data:
                person_data["extraction_id"] = f"ext_{uuid4().hex[:8]}"

            # Validate and fix source references
            source_refs = person_data.get("source_references", [])
            validated_refs = []

            for ref in source_refs:
                # Ensure document_id is valid
                doc_id = ref.get("document_id", "")
                if doc_id not in doc_lookup and documents:
                    # Use first document as fallback
                    doc_id = documents[0].document_id
                    ref["document_id"] = doc_id
                    ref["filename"] = documents[0].filename

                # Ensure page_number is valid
                page_num = ref.get("page_number", 1)
                if not isinstance(page_num, int) or page_num < 1:
                    ref["page_number"] = 1

                validated_refs.append(SourceReference(**ref))

            # Ensure at least one source reference
            if not validated_refs and documents:
                validated_refs.append(
                    SourceReference(
                        document_id=documents[0].document_id,
                        filename=documents[0].filename,
                        page_number=1,
                    )
                )

            person_data["source_references"] = validated_refs

            # Create ExtractedPerson
            person = ExtractedPerson(**person_data)
            extracted_persons.append(person)

        except Exception as e:
            logger.warning(f"Failed to parse person {i}: {e}")
            logger.debug(f"Person data: {person_data}")
            # Continue with other persons

    return extracted_persons


async def extract_persons_async(
    documents: list[DocumentInput],
    retry_feedback: str | None = None,
) -> ExtractorOutput:
    """Extract persons from documents using LLM (async).

    Args:
        documents: Documents to process.
        retry_feedback: Optional feedback from previous attempt.

    Returns:
        ExtractorOutput with extracted persons.

    Raises:
        Exception: If extraction fails.
    """
    logger.info(f"Starting extraction from {len(documents)} document(s)")

    # Render prompt
    prompt = render_prompt(documents, retry_feedback)

    # Get LLM provider
    llm = get_llm_provider()

    # Call LLM
    messages = [Message(role="user", content=prompt)]
    response = await llm.complete_async(messages)

    # Parse response
    extracted_persons = parse_llm_response(response.content, documents)

    logger.info(f"Extracted {len(extracted_persons)} person(s)")

    return ExtractorOutput(extracted_persons=extracted_persons)


def extract_persons(
    documents: list[DocumentInput],
    retry_feedback: str | None = None,
) -> ExtractorOutput:
    """Extract persons from documents using LLM (sync).

    Args:
        documents: Documents to process.
        retry_feedback: Optional feedback from previous attempt.

    Returns:
        ExtractorOutput with extracted persons.

    Raises:
        Exception: If extraction fails.
    """
    logger.info(f"Starting extraction from {len(documents)} document(s)")

    # Render prompt
    prompt = render_prompt(documents, retry_feedback)

    # Get LLM provider
    llm = get_llm_provider()

    # Call LLM
    messages = [Message(role="user", content=prompt)]
    response = llm.complete(messages)

    # Parse response
    extracted_persons = parse_llm_response(response.content, documents)

    logger.info(f"Extracted {len(extracted_persons)} person(s)")

    return ExtractorOutput(extracted_persons=extracted_persons)


def extractor_agent(state: WorkflowState) -> WorkflowState:
    """Extractor agent function for LangGraph workflow.

    This function:
    1. Gets documents from state
    2. Gets any retry feedback from previous attempt
    3. Calls LLM to extract persons
    4. Updates state with extracted persons

    Args:
        state: Current workflow state.

    Returns:
        Updated workflow state with extracted persons.
    """
    workflow_id = state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Extractor agent starting")

    # Get documents from state
    documents = state.get("documents", [])
    if not documents:
        logger.warning(f"[{workflow_id}] No documents to process")
        return update_extraction_result(state, [])

    # Get retry feedback if any
    retry_feedback = get_feedback(state, "extraction")

    # Extract persons
    try:
        output = extract_persons(documents, retry_feedback)
        logger.info(
            f"[{workflow_id}] Extracted {len(output.extracted_persons)} person(s)"
        )
        return update_extraction_result(state, output.extracted_persons)

    except Exception as e:
        logger.error(f"[{workflow_id}] Extraction failed: {e}", exc_info=True)
        # Return empty list on failure - critic will handle
        return update_extraction_result(state, [])


async def extractor_agent_async(state: WorkflowState) -> WorkflowState:
    """Async extractor agent function for LangGraph workflow.

    Args:
        state: Current workflow state.

    Returns:
        Updated workflow state with extracted persons.
    """
    workflow_id = state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Extractor agent starting (async)")

    # Get documents from state
    documents = state.get("documents", [])
    if not documents:
        logger.warning(f"[{workflow_id}] No documents to process")
        return update_extraction_result(state, [])

    # Get retry feedback if any
    retry_feedback = get_feedback(state, "extraction")

    # Extract persons
    try:
        output = await extract_persons_async(documents, retry_feedback)
        logger.info(
            f"[{workflow_id}] Extracted {len(output.extracted_persons)} person(s)"
        )
        return update_extraction_result(state, output.extracted_persons)

    except Exception as e:
        logger.error(f"[{workflow_id}] Extraction failed: {e}", exc_info=True)
        # Return empty list on failure - critic will handle
        return update_extraction_result(state, [])
