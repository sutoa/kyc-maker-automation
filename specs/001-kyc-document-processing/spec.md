# Feature Specification: KYC Document Processing Agentic Workflow

**Feature Branch**: `001-kyc-document-processing`
**Created**: 2025-03-22
**Status**: Draft
**Input**: KYC Document Processing — Agentic Application Requirements (v4) from ai-docs/prd.md

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Process Documents and Extract Person Data (Priority: P1)

A KYC Ops user uploads one or more documents (PDF or TXT files) containing information about natural persons. Documents may be in German or English (MVP focuses on German HandelsRegister documents). The system automatically extracts all personal information from these documents, recording where each piece of data was found (source document and page number). A quality review ensures all mandatory fields are present before proceeding.

**Why this priority**: This is the foundational capability. Without accurate extraction with provenance tracking, no downstream processing (deduplication, classification) can occur. This delivers immediate value by automating the most time-consuming manual task.

**Independent Test**: Can be fully tested by uploading sample German HandelsRegister documents and verifying that extracted person records include all mandatory fields (First Name, Last Name, Source Document, Page Number) with correct source references.

**Acceptance Scenarios**:

1. **Given** a KYC Ops user has a PDF document containing person information, **When** they upload the document and trigger processing, **Then** the system extracts all persons with their First Name, Last Name, Source Document, and Page Number recorded for each data point.

2. **Given** a document contains optional fields (Job Title, Date of Birth, Nationality, Address), **When** the system processes the document, **Then** these fields are extracted where available and linked to their source location.

3. **Given** the same person appears on multiple pages or in multiple documents, **When** the system processes the documents, **Then** each occurrence is recorded separately with its own source document and page number.

4. **Given** an extraction is missing mandatory fields, **When** the quality reviewer (Critic agent) evaluates the output, **Then** the extraction is sent back with specific feedback for correction (up to 4 retry attempts).

5. **Given** extraction has failed 4 times, **When** the quality reviewer evaluates the output, **Then** the workflow transitions to a Failed state with all attempts and feedback logged.

6. **Given** a German HandelsRegister document, **When** the system processes it, **Then** person names and roles are correctly extracted regardless of German language formatting (e.g., "Geschäftsführer" for Managing Director).

---

### User Story 2 - Deduplicate and Reconcile Person Records (Priority: P2)

After extraction, the system identifies individuals who appear multiple times within or across documents. True duplicates are merged while preserving all unique source references. When conflicting information exists for the same person (e.g., different addresses in different documents), the system flags these conflicts with full source details.

**Why this priority**: Deduplication must happen before classification to ensure each person is classified exactly once. This prevents compliance issues from duplicate or conflicting classifications.

**Independent Test**: Can be tested with documents containing the same person multiple times with varying information, verifying that duplicates are merged and conflicts are flagged with source references.

**Acceptance Scenarios**:

1. **Given** extracted records contain the same person appearing in multiple documents, **When** reconciliation runs, **Then** the person appears once in the output with all source documents and page numbers consolidated.

2. **Given** the same person has different values for a field across documents (e.g., two different addresses), **When** reconciliation runs, **Then** the conflict is flagged with both values and their respective source document and page numbers.

3. **Given** reconciliation output fails quality review, **When** the Critic agent provides feedback, **Then** the reconciliation agent retries with the feedback (up to 4 attempts).

---

### User Story 3 - Classify Persons as CSM or Non-CSM (Priority: P3)

Each deduplicated person record is classified as either CSM (Client Senior Manager) or Non-CSM based on the official KYC definition. The classification decision includes explicit reasoning explaining which conditions from the CSM definition were met or not met, with supporting evidence (job title, responsibilities, source references).

**Why this priority**: Classification is the business outcome that KYC Ops needs. It depends on accurate extraction and deduplication being complete first.

**Independent Test**: Can be tested with person records containing various job titles and responsibilities, verifying that each receives a CSM or Non-CSM classification with explicit reasoning.

**Acceptance Scenarios**:

1. **Given** a deduplicated person record with job title "Chief Financial Officer", **When** classification runs, **Then** the person is classified as CSM with reasoning citing the specific CSM definition criteria that apply.

2. **Given** a person record with job title "Administrative Assistant", **When** classification runs, **Then** the person is classified as Non-CSM with reasoning explaining why CSM criteria are not met.

3. **Given** a person record without a job title, **When** classification runs, **Then** the system uses available information (responsibilities, context) to make a classification with explicit reasoning about the decision basis.

4. **Given** classification output fails quality review, **When** the Critic agent provides feedback, **Then** the classifier retries with the feedback (up to 4 attempts).

---

### User Story 4 - View Final Categorized Output (Priority: P4)

The system produces a complete output package containing: (1) a Document Manifest listing all original documents received with their processing status, and (2) two structured person lists: CSM and Non-CSM. Each person entry includes the complete record (all extracted fields), all source references, the classification outcome, and the explicit reasoning for the classification decision.

**Why this priority**: This is the final deliverable that KYC Ops consumes. It depends on all prior steps completing successfully.

**Independent Test**: Can be tested by completing a full workflow and verifying the output contains the document manifest plus two person lists with complete records, source provenance, and classification reasoning.

**Acceptance Scenarios**:

1. **Given** a workflow has completed successfully, **When** the user views the output, **Then** they see a Document Manifest listing all uploaded documents with their filename, file type, page count, and processing status.

2. **Given** a workflow has completed successfully, **When** the user views the output, **Then** they see a CSM list and a Non-CSM list, each containing complete person records.

3. **Given** a person in the output, **When** the user examines their record, **Then** they can see all source documents and page numbers where this person was found, plus the classification reasoning.

---

### User Story 5 - Monitor Workflow Progress in Real-Time (Priority: P5)

KYC Ops users can see the live status of any running workflow. A graph view shows agents as nodes with animated transitions between them. A trace detail view shows a timeline of all steps with expandable input/output details. Both views update in real-time without page refresh.

**Why this priority**: Observability is critical for compliance and debugging, but the core processing must work first.

**Independent Test**: Can be tested by starting a workflow and observing real-time updates in both graph and trace views.

**Acceptance Scenarios**:

1. **Given** a workflow is in progress, **When** the user views the graph, **Then** the currently executing agent is visually highlighted and transitions animate when execution moves between agents.

2. **Given** a workflow step has retried, **When** the user views the trace, **Then** they see the retry cycles as indented sub-rows with the original output, critic feedback, and corrected output.

3. **Given** a workflow has failed, **When** the user views the status, **Then** the failed step is clearly indicated with the failure reason and all retry history visible.

---

### User Story 6 - Browse and Review Past Workflows (Priority: P6)

KYC Ops users can view a list of all past workflow runs showing status (completed, failed, pending), files uploaded, trigger timestamp, and duration. They can drill into any past run to see the full trace and outputs.

**Why this priority**: Historical review supports audit requirements but is not needed for basic operation.

**Independent Test**: Can be tested by running multiple workflows and verifying the history list shows all runs with correct metadata.

**Acceptance Scenarios**:

1. **Given** multiple workflows have run, **When** the user views the workflow history, **Then** they see a list with each run's timestamp, status, uploaded files, and duration.

2. **Given** the user selects a past workflow, **When** they view its details, **Then** they see the complete trace including all agent inputs/outputs, timing, and any retry cycles.

---

### Edge Cases

- What happens when a document contains no identifiable persons? The system completes with an empty result set and logs that no persons were found.
- What happens when a document is corrupted or unreadable? The workflow fails with a clear error message identifying the problematic file.
- What happens when mandatory fields cannot be extracted for any person? The extraction fails quality review and retries; after 4 failures, the workflow enters Failed state with detailed logging.
- What happens when all extracted persons have conflicting information? All conflicts are flagged; the workflow continues but the output clearly indicates unresolved conflicts requiring human review.
- What happens when a person cannot be classified due to insufficient information? The classifier makes a best-effort decision with explicit reasoning about the limitations, or flags for human review if no reasonable determination is possible.
- What happens when the LLM service (OpenAI/Gemini) is unavailable? The system retries with exponential backoff (up to 3 attempts), then fails the workflow with a clear error message indicating service unavailability.

## Requirements *(mandatory)*

### Functional Requirements

**Document Processing**

- **FR-001**: System MUST accept PDF (.pdf) and plain text (.txt) file uploads for MVP
- **FR-002**: System MUST support uploading multiple files to initiate a single workflow run
- **FR-003**: System MUST extract text content from uploaded documents while preserving page boundaries
- **FR-003a**: System MUST support multi-language documents, specifically German and English for MVP
- **FR-003b**: System MUST correctly extract information from German HandelsRegister (Commercial Register) documents as the primary MVP use case

**Information Extraction**

- **FR-004**: System MUST extract First Name and Last Name as mandatory fields for every identified person
- **FR-005**: System MUST extract Job Title, Date of Birth, Nationality, Address, and other personal information when available
- **FR-006**: System MUST record the source document filename and page number for every extracted data point
- **FR-007**: System MUST record each occurrence separately when the same person appears multiple times

**Quality Control**

- **FR-008**: System MUST implement a Critic agent that reviews output at every workflow step
- **FR-009**: Critic agents MUST implement three outcomes: pass (proceed), fail-retry (return with feedback), fail-maxed (terminate workflow)
- **FR-010**: System MUST cap retry attempts at 4 per step
- **FR-011**: System MUST log every retry cycle with original output, critic feedback, corrected output, and retry count

**Data Reconciliation**

- **FR-012**: System MUST identify and merge duplicate person records while preserving all source references
- **FR-012a**: System MUST use fuzzy name matching to identify duplicate persons (e.g., "Hans Müller" and "Hans Mueller" are treated as potential duplicates)
- **FR-013**: System MUST detect and flag conflicting information for the same person with source details for each value

**Classification**

- **FR-014**: System MUST classify each unique person as CSM or Non-CSM based on the official KYC definition
- **FR-015**: System MUST include explicit reasoning for every classification decision citing specific criteria
- **FR-016**: System MUST ensure each person appears exactly once in the final output (either CSM or Non-CSM list)

**Output**

- **FR-017**: System MUST produce two structured lists: CSM and Non-CSM
- **FR-018**: Each output record MUST include all extracted fields, all source references, classification outcome, and reasoning
- **FR-018a**: System MUST include a Document Manifest in the final output listing all original documents received by the extractor
- **FR-018b**: Document Manifest MUST include for each document: filename, file type, page count, and processing status (successfully processed / failed / partially processed)
- **FR-018c**: System MUST provide the final output as a downloadable JSON file

**Agent Configuration**

- **FR-019**: All agents MUST be defined via configuration files, not hardcoded in application logic
- **FR-020**: Agent configurations MUST support both inline prompts and external prompt file references
- **FR-021**: Agent configurations MUST define conditional transitions between agents

**Observability**

- **FR-022**: System MUST provide a graph view showing agents as nodes and transitions as edges
- **FR-023**: System MUST provide a trace detail view showing timeline of steps with expandable details
- **FR-024**: Both views MUST update in real-time during workflow execution
- **FR-025**: System MUST maintain a browsable history of all workflow runs

**Auditability**

- **FR-026**: System MUST generate a complete audit log for every workflow run
- **FR-027**: Audit logs MUST include timestamps, agent actions, inputs/outputs, decisions, and reasoning
- **FR-028**: Source document and page number provenance MUST be preserved throughout the entire workflow
- **FR-029**: System MUST retain all workflow results, audit logs, and source documents for 7 years from workflow completion (KYC compliance requirement)

### Key Entities

- **Person**: A natural person identified in documents. Attributes: First Name (mandatory), Last Name (mandatory), Job Title, Date of Birth, Nationality, Address, other personal info. Has many Source References.

- **Source Reference**: Links extracted data to its origin. Attributes: Document filename, Page number. Belongs to a Person and specific data field.

- **Workflow Run**: A single execution of the document processing pipeline. Attributes: Trigger timestamp, Status (pending/in-progress/completed/failed), Duration, Uploaded files. Has many Agent Executions.

- **Agent Execution**: A single invocation of an agent within a workflow. Attributes: Agent name, Start time, End time, Input payload, Output payload, Retry count. May have Critic Feedback.

- **Critic Feedback**: Feedback from a Critic agent on a failed review. Attributes: Issues identified, Suggested corrections, Retry number.

- **Classification Result**: The CSM/Non-CSM determination for a person. Attributes: Outcome (CSM or Non-CSM), Reasoning, Supporting evidence references.

- **Document Manifest**: A summary of all documents received for processing. Attributes: Filename, File type (PDF/TXT), Page count, Processing status (successfully processed/failed/partially processed). Included in final output.

## Clarifications

### Session 2025-03-22

- Q: How should the system determine if two extracted records refer to the same person? → A: Fuzzy match on name only
- Q: How should users authenticate and what access control is needed? → A: No authentication for MVP (single user, network-restricted)
- Q: How should the workflow behave when the LLM service is unavailable? → A: Retry with exponential backoff (3 attempts), then fail with clear error
- Q: How long should workflow results and audit logs be retained? → A: 7 years from workflow completion (KYC compliance standard)
- Q: In what format should the final output be delivered to users? → A: JSON file download

## Assumptions

- MVP assumes single user, no authentication required (network-restricted internal tool); multi-user auth deferred to post-MVP
- The official KYC/CSM definition document exists and will be provided as reference material for the classification agent's prompts
- Documents are in German or English; MVP focuses on German HandelsRegister documents
- The LLM used supports German and English language processing
- File sizes are reasonable for processing (not multi-gigabyte files)
- The KYC Ops team has web browser access to use the UI
- Network latency for real-time updates is acceptable over standard internet connections

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Extraction accuracy for mandatory fields (First Name, Last Name, Source Document, Page Number) reaches 99% or higher on test document sets
- **SC-002**: Users can complete a full workflow (upload to final output) in under 5 minutes for typical document sets (1-10 pages)
- **SC-003**: Every classification decision includes explicit reasoning that an auditor can trace back to source documents
- **SC-004**: 95% of workflows complete successfully without requiring manual intervention
- **SC-005**: Workflow status updates appear in the UI within 2 seconds of state changes
- **SC-006**: Users can locate and review any past workflow within 30 seconds using the history view
- **SC-007**: Conflicting information is detected and flagged in 100% of cases where the same person has different values across documents
- **SC-008**: Zero persons appear in both CSM and Non-CSM lists (mutual exclusivity enforced)
- **SC-009**: Extraction accuracy for German HandelsRegister documents matches or exceeds English document accuracy (99%+ for mandatory fields)
- **SC-010**: Every final output includes a complete Document Manifest listing 100% of originally uploaded documents
