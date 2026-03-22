<!--
================================================================================
SYNC IMPACT REPORT
================================================================================
Version Change: 1.0.0 → 1.1.0 (MINOR - new principle added, sections simplified)

Added Principles:
- IX. Model-Agnostic AI Implementation - Support for multiple LLM providers

Removed Sections:
- Governance > Amendment Process
- Governance > Versioning Policy
- Governance > Compliance Review
- Development & Testing Standards > CI/CD Requirements

Modified Sections:
- Governance simplified to Runtime Guidance only

Templates Requiring Updates:
- .specify/templates/plan-template.md: ✅ Compatible
- .specify/templates/spec-template.md: ✅ Compatible
- .specify/templates/tasks-template.md: ✅ Compatible

Follow-up TODOs: None
================================================================================
-->

# KYC Maker Automation Constitution

## Core Principles

### I. Accuracy First

All AI agent outputs MUST be verifiable against source documents. Every extracted data point MUST include provenance (source document and page number). Classification decisions MUST include explicit reasoning tied to official definitions. No data transformation or inference is permitted without traceability to original source material.

**Rationale**: KYC compliance requires auditability. Regulators and compliance officers must be able to trace any output back to its source.

### II. Multi-Agent Quality Gates

Every workflow step MUST pass through a dedicated Critic agent before proceeding. Critic agents MUST implement three-outcome routing: pass, retry (with feedback), or fail. Maximum retry attempts MUST be capped (default: 4) to prevent infinite loops. All retry cycles MUST be fully logged with original output, critic feedback, and corrected output.

**Rationale**: Unlike "vibe coding," KYC applications require systematic quality assurance at every step, not just end-to-end testing.

### III. Declarative Agent Configuration

All agents MUST be defined via configuration files (YAML preferred), not hardcoded in application logic. Agent definitions MUST include: name, role, goal, prompt (inline or file reference), tools, output_key, dependencies, and transitions. Conditional routing logic MUST be expressed declaratively in agent configuration. Prompts MAY be inline for short prompts or referenced from external files for longer prompts.

**Rationale**: Declarative configuration enables version control, auditability, and non-engineer review of agent behavior.

### IV. Observability by Design

Every agent invocation MUST be traced with: input payload, output payload, timing, and decision metadata. Workflow state MUST be observable in real-time during execution. Failed workflows MUST preserve complete trace history including all retry attempts and failure reasons. Tracing infrastructure MUST support self-hosting or data residency controls for sensitive KYC data.

**Rationale**: KYC workflows handle sensitive personal data. Full observability enables debugging, compliance audits, and continuous improvement.

### V. Test-First Development

All agent behaviors MUST have corresponding test cases before implementation. Contract tests MUST verify agent input/output schemas. Integration tests MUST cover critic feedback loops and retry scenarios. Unit tests MUST cover individual tool functions and data transformations.

**Rationale**: KYC accuracy requirements demand rigorous testing discipline. Manual testing is insufficient for compliance-critical systems.

### VI. Consistency & Deduplication

Data reconciliation agents MUST identify and flag duplicate records across documents. Conflicting information for the same entity MUST be detected and flagged with all source references. The system MUST NOT silently merge or overwrite conflicting data without explicit rules. Final outputs MUST present each unique entity exactly once with all source references consolidated.

**Rationale**: KYC decisions must be based on consistent, deduplicated data. Undetected conflicts can lead to compliance failures.

### VII. Structured Error Handling

All errors MUST be categorized: recoverable (retry), unrecoverable (fail workflow), or deferred (flag for human review). Error messages MUST include: error type, affected data, source location, and suggested remediation. Workflow failures MUST NOT lose work; partial results MUST be preserved and resumable. Human escalation paths MUST be defined for errors that cannot be automatically resolved.

**Rationale**: KYC workflows cannot simply crash. Graceful degradation and clear error communication are essential for operations teams.

### VIII. Security & Data Protection

KYC personal data MUST NOT be logged in plaintext in general application logs. Sensitive fields MUST be redacted or encrypted in observability traces unless explicitly authorized. All external API calls MUST use secure transport (TLS 1.2+). Agent configurations containing prompts MUST NOT include actual customer data; use placeholders and schemas only.

**Rationale**: KYC data includes PII and sensitive financial information. Security is non-negotiable.

### IX. Model-Agnostic AI Implementation

All AI/LLM integrations MUST be provider-agnostic. The codebase MUST support switching between model providers (OpenAI, Gemini, etc.) via configuration, not code changes. LLM client code MUST use an abstraction layer that normalizes API differences. Model selection MUST be configurable via environment variables or configuration files.

**Rationale**: Different environments have different model access (e.g., OpenAI at home, Gemini at work). The system must work seamlessly across providers without code modifications.

## Quality & Compliance Requirements

### Accuracy Standards

- Extraction accuracy target: ≥99% for mandatory fields (First Name, Last Name, Source Document, Page Number)
- Classification decisions MUST include explicit reasoning
- All outputs MUST be traceable to source documents

### Audit Trail Requirements

- Every workflow run MUST generate a complete audit log
- Audit logs MUST include: timestamp, agent actions, inputs/outputs, decisions, and reasoning
- Audit logs MUST be immutable once workflow completes
- Retention period: As defined by compliance requirements (minimum 7 years recommended)

### Data Quality Rules

- Mandatory fields MUST be validated before workflow proceeds
- Optional fields MUST be extracted when available but not block workflow on absence
- Conflicting data MUST be flagged, not silently resolved

## Development & Testing Standards

### Code Quality

- Python 3.11+ with type hints on all public functions
- Code MUST pass static analysis (ruff, mypy) with zero errors
- All modules MUST have docstrings explaining purpose and usage
- Configuration files MUST be validated against schemas before use

### Testing Pyramid

| Level | Scope | Requirement |
|-------|-------|-------------|
| Unit | Individual functions, tools, utilities | All pure functions MUST have unit tests |
| Contract | Agent input/output schemas | All agents MUST have contract tests |
| Integration | Agent chains, feedback loops | All critic-agent interactions MUST have integration tests |
| E2E | Full workflow with sample documents | Each workflow path MUST have at least one E2E test |

### Tracing & Monitoring

- Use structured logging (JSON format) for all agent operations
- Implement distributed tracing with correlation IDs across agent invocations
- Metrics MUST include: latency per agent, retry rates, failure rates, extraction confidence scores
- Dashboards MUST surface workflow health and quality metrics

## Runtime Guidance

- Agent configuration schemas are defined in `config/schemas/`
- Prompt templates are stored in `prompts/`
- Model provider is configured via `LLM_PROVIDER` environment variable (values: `openai`, `gemini`)
- For development workflow guidance, refer to `.specify/` templates

**Version**: 1.1.0 | **Ratified**: 2025-03-22 | **Last Amended**: 2025-03-22
