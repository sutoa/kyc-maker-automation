# KYC Document Processing — Agentic Application Requirements (v4)

## 1. Business Context

This application is for a **KYC (Know Your Customer)** operations team. **KYC Ops users** currently handle large volumes of documents manually. The goal is to automate and orchestrate the end-to-end KYC document processing workflow using an agentic AI system built in Python.

---

## 2. Workflow Overview

### Step 1 — Information Extraction

Two dedicated agents work in tandem:

#### Agent 1A — Extractor

Extract the following named entity (natural person) data points from documents. For every piece of information extracted, the agent must record **source provenance**:

| Field | Requirement |
|---|---|
| First Name | **Mandatory** |
| Last Name | **Mandatory** |
| Job Title | Optional — retrieve if available |
| Date of Birth | Optional — retrieve if available |
| Nationality | Optional — retrieve if available |
| Address | Optional — retrieve if available |
| Other personal info | Optional — retrieve if available |
| **Source Document** | **Mandatory** — filename or document identifier |
| **Page Number** | **Mandatory** — the page within that document where the information was found |

If the same person appears across multiple documents or pages, each occurrence is recorded with its own source document and page number.

#### Agent 1B — Critic 1 (Field Validator + Quality Reviewer)

Subsumes the field validation responsibility. Reviews the Extractor's output to:
- Verify all mandatory fields (First Name, Last Name, Source Document, Page Number) are present for every record
- Flag records where any mandatory field is missing
- Assess overall extraction quality
- Apply the feedback loop routing logic (pass / retry / fail) described in Section 3

---

### Step 2 — Data Reconciliation & Cleanup

- **Deduplication:** Identify individuals appearing multiple times within or across documents; remove true redundancies while preserving all unique source references
- **Conflict Detection:** Flag conflicting information for the same individual (e.g. different values for the same field across documents), noting the source document and page number for each conflicting value

---

### Step 3 — Classification (CSM vs. Non-CSM)

Classify each individual as **CSM (Client Senior Manager)** or **Non-CSM** based on the official KYC definition, evaluated primarily against job title (where available) and stated responsibilities.

**Every classification decision must include:**
- The outcome: CSM or Non-CSM. 
- Each person should only appear ONCE, either as CSM or Non-CSM
- **Explicit reasoning** — which specific conditions from the official KYC/CSM definition were met or not met
- Supporting evidence — source document, page number, job title or responsibilities that drove the decision

---

### Step 4 — Final Output

Two structured lists: **CSM** and **Non-CSM**. Each entry includes the **complete extracted record**:

| Field | Notes |
|---|---|
| First Name | Mandatory |
| Last Name | Mandatory |
| Job Title | If available |
| Date of Birth | If available |
| Nationality | If available |
| Address | If available |
| Any other extracted fields | If available |
| Source Document(s) | All documents where this person was found |
| Page Number(s) | Corresponding pages per source document |
| Classification | CSM or Non-CSM |
| Classification Reasoning | Explicit explanation tied to the official CSM definition |

---

## 3. Quality Control — Feedback Loops

A **Critic Agent** reviews the output at every step. The Critic has exactly **three possible outcomes** per review, with a **maximum retry limit of 4 attempts** per step:

| Condition | Outcome | Next Action |
|---|---|---|
| Output passes review | ✅ Pass | Proceed to the next step in the workflow |
| Output fails AND retry count < 4 | ❌ Fail — Retry | Send targeted feedback back to the originating agent; increment retry counter |
| Output fails AND retry count = 4 | 💀 Fail — Max Retries Reached | Transition the workflow to a **Failed state**; log all attempts, feedback, and final failure reason |

- Every retry cycle is fully logged: original output, critic feedback, corrected output, and retry count
- Feedback loops apply to: Extractor (via Critic 1), Reconciliation Agent (via Critic 2), and Classifier (via Critic 3)
- A failed workflow is surfaced clearly in the UI with the step, retry history, and failure reason visible

---

## 4. Supported File Types

| Phase | Supported Formats |
|---|---|
| **MVP** | PDF (.pdf), Plain text (.txt) |
| **Post-MVP** | Excel (.xlsx), Word (.docx) |

---

## 5. Agent Configuration

### Goals

All agents must be **declaratively configurable** — definitions, relationships, prompts, tools, and routing logic must live in config files, not be hardcoded in application logic.

### Format

- **YAML is the default**, but TOML, JSON, or a well-designed custom schema are acceptable
- Must be human-readable, version-controllable, and expressive enough to fully describe an agent without touching Python code
- Inspired by CrewAI, LangGraph, and Google ADK agent specification patterns — the final attribute list must be validated against those frameworks before implementation

### ⚠️ Important Note on the YAML Examples

The YAML examples in this document are **illustrative only**. They demonstrate intent and the kinds of attributes needed. Before implementation, the development team must:

1. Study the agent specification formats used in **LangGraph**, **CrewAI**, and **Google ADK**
2. Adopt or adapt the most sensible, framework-aligned set of attributes
3. Note that some fields (e.g. `inputs`) may not be standard in all frameworks; `outputs` may use session state key references rather than typed schemas
4. The final agent spec format should be a deliberate design decision, documented separately before coding begins

---

### Prompt Storage — Flexible Options

| Option | Description | When to Use |
|---|---|---|
| **Inline** | Prompt text written directly in the config file | Short or simple prompts; MVP default |
| **File Reference** | A path to an external `.txt` or `.md` file | Long prompts that would make the config file unwieldy |

Both options must be supported from day one. For MVP, inline prompts are acceptable.

```yaml
# Option A — inline prompt
- name: extractor
  prompt: |
    You are a KYC data extraction specialist...

# Option B — external file reference
- name: classifier
  prompt_file: prompts/classifier_prompt.md
```

---

### Illustrative Agent Attributes

The following attributes represent the **intent** of what each agent definition should capture. Final field names and structure must be confirmed against framework conventions:

| Attribute | Description |
|---|---|
| `name` | Unique agent identifier |
| `role` | Short description of what the agent does |
| `goal` | What the agent is trying to achieve |
| `backstory` / `context` | Background framing (as in CrewAI-style specs) |
| `prompt` | Inline instruction prompt *(mutually exclusive with `prompt_file`)* |
| `prompt_file` | Path to external prompt file *(mutually exclusive with `prompt`)* |
| `tools` | Tools this agent can invoke (e.g. `pdf_reader`, `text_parser`) |
| `output_key` | The key name in shared session state where this agent writes its output |
| `dependencies` | Upstream agents this agent depends on |
| `transitions` | Explicit conditional routing rules to other agents (see below) |

---

### Agent Relationships & Conditional Routing

Relationships between agents are expressed as **explicit conditional transitions**, analogous to how LangGraph represents conditional edges between nodes. Each agent defines a `transitions` block describing every possible next step and the condition that triggers it.

#### Illustrative Example — Critic Agent Transitions

```yaml
- name: critic_1
  role: Extraction Quality Reviewer and Field Validator
  goal: >
    Review the extractor's output for completeness and quality.
    Verify all mandatory fields are present and flag any issues.
  prompt_file: prompts/critic_1_prompt.md
  tools:
    - quality_checker
  output_key: critic_1_decision
  transitions:
    - condition: decision == "pass"
      next: reconciler

    - condition: decision == "fail" AND retry_count < 4
      next: extractor
      action: increment_retry_count
      action: write_feedback_to_state

    - condition: decision == "fail" AND retry_count >= 4
      next: FAILED
      action: log_failure_reason
```

#### Illustrative Example — Extractor Agent

```yaml
- name: extractor
  role: Named Entity Extractor
  goal: >
    Extract all personal information about natural persons from input documents,
    recording source document name and page number for every data point.
  backstory: >
    You are a senior KYC analyst specialising in extracting personal information
    from financial and legal documents.
  prompt: |
    You are a KYC data extraction specialist. For each document provided,
    identify all natural persons and extract: first name (mandatory), last name
    (mandatory), and where available: job title, date of birth, nationality,
    address, and any other personal details. For every extracted value, record
    the source document filename and the exact page number where the information
    was found.
  tools:
    - pdf_reader
    - text_parser
  output_key: extracted_persons
  transitions:
    - condition: always
      next: critic_1
```

---

### Workflow Routing Map

Each Critic is **dedicated to one agent** and loops back exclusively to that agent on failure. No Critic ever routes a retry to a downstream agent.

```
                    ┌──────────────────────────────┐
                    │      (retry, count < 4)       │
                    ▼                               │
               extractor ──────────► critic_1 ──────┘
                                         │
                                 pass    │    fail + maxed
                                         │
                                 ┌───────┴────────┐
                                 ▼                ▼
                            reconciler          FAILED
                                 │
                    ┌──────────────────────────────┐
                    │      (retry, count < 4)       │
                    ▼                               │
               reconciler ─────────► critic_2 ──────┘
                                         │
                                 pass    │    fail + maxed
                                         │
                                 ┌───────┴────────┐
                                 ▼                ▼
                            classifier          FAILED
                                 │
                    ┌──────────────────────────────┐
                    │      (retry, count < 4)       │
                    ▼                               │
               classifier ─────────► critic_3 ──────┘
                                         │
                                 pass    │    fail + maxed
                                         │
                                 ┌───────┴────────┐
                                 ▼                ▼
                        output_formatter        FAILED
```

**Reading the diagram:**

| Arrow | Meaning |
|---|---|
| `agent ──► critic` | Agent submits output to its Critic for review |
| `critic ──► next_agent` | Critic passes — workflow advances to the next stage |
| `critic ──► same_agent` (loop back ↑) | Critic fails — output returned to the same agent that produced it, with feedback; retry counter incremented |
| `critic ──► FAILED` | Critic fails AND retry count has reached 4 — workflow terminates in a Failed state |

---

## 6. Tracing & Observability UI

### Workflow List View

- Browsable list of all past workflow runs (completed, failed, pending)
- Each run shows: trigger timestamp, files uploaded, current status, total duration

### Workflow Detail View

Per workflow run, display:
- All agents and steps involved
- Execution count per step (including retries)
- Timing per step (start, end, duration)
- Full input and output at each step (expandable)
- Critic feedback messages — what was flagged, what correction was requested, which retry number

### Live / In-Progress Workflow View

**Node states:**

| State | Visual |
|---|---|
| Pending | Grey, inactive |
| Currently executing | Pulsing / animated highlight on the node |
| Active transition | The **edge line between nodes flashes or animates** (e.g. moving dot along the arrow) |
| Completed | Solid green |
| Failed / max retries | Solid red |
| Sent back by Critic (retry) | Orange / amber with retry count badge |

Updates must be real-time — no manual page refresh required.

---

## 7. Core UI Features

| Feature | Description |
|---|---|
| **Multi-file Upload** | Upload multiple PDFs and/or .txt files to initiate one workflow run |
| **Trigger Workflow** | Explicit action to start the processing pipeline |
| **Workflow History** | List of all past runs with status, files, and timing |
| **Live Monitoring** | Real-time view with both Graph View and Trace Detail View |

---

## 8. Target UI Design — Combining Two Reference Products

The application UI should offer **two synchronized views** for any workflow run, combining the best elements of the two identified reference products:

### Graph View *(inspired by LangGraph Studio)*

- Interactive node-edge diagram — each agent is a node, each conditional transition is a directed edge
- Edge labels showing the condition that triggers that route (e.g. "pass", "fail + retry", "fail + maxed")
- **Live animation on active edges** — when execution is transitioning between two agents, the connecting arrow flashes, pulses, or shows a moving dot
- Node color-coding per the state table in Section 6

### Trace Detail View *(inspired by LangSmith / Dell Technologies example)*

- Flat timeline / list of all steps in execution order
- Each step is expandable to reveal: full input payload, full output payload, timing, retry number, and Critic feedback if applicable
- Retry cycles shown as indented sub-rows under the parent step, making the feedback loop history easy to read

Both views reflect the same live state simultaneously and can be toggled or displayed side-by-side.

---

## 9. Framework Recommendation

### Under Consideration

1. **LangChain + LangGraph** — graph-based multi-agent orchestration with native LangSmith observability
2. **Google ADK (Agent Development Kit)** — Google's open-source framework with built-in web UI and Cloud Trace integration

### Evaluation Criteria

| Criteria | Why It Matters |
|---|---|
| Multi-agent orchestration | Multiple specialised agents must coordinate in sequence |
| Conditional routing / feedback loops | Critic's three-outcome routing (pass / retry / fail) must be natively expressible |
| Declarative agent config | YAML-based definitions with prompt file referencing |
| Built-in tracing / observability | Required for the audit trail and the live monitoring UI |
| Tool assignment per agent | PDF parsing, text extraction, deduplication tools |
| Active ecosystem | Long-term supportability |

> A detailed framework recommendation with justification against each criterion should be produced as a separate deliverable after studying LangGraph, CrewAI, and Google ADK agent specification formats.

---

## 10. Non-Functional Requirements

| Requirement | Detail |
|---|---|
| **Accuracy** | Critical — KYC compliance; Critic reviews every step with a max retry limit of 4 |
| **Auditability** | Full trace of every agent action, retry cycle, critic feedback, and classification reasoning, with source document and page number preserved throughout |
| **Transparency** | Classification decisions must include explicit reasoning tied to the official CSM definition |
| **Maintainability** | All agents defined via config; prompts storable inline or in separate files |
| **Extensibility** | Easy to add new agents, steps, or file formats post-MVP |
| **Data Sensitivity** | KYC data — observability tooling must support self-hosting or data residency controls where required |
