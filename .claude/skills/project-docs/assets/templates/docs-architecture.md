# Architecture

## Overview

[2–3 paragraphs covering:
 1. What the system does at a high level — the problem domain and the overall approach
 2. The core design decisions that shape the architecture — what is in-process vs external,
    what is synchronous vs async, what is stateful vs stateless
 3. Why these choices were made — the constraints or goals that drove the design

Write as if explaining to a senior engineer joining the team. Do not repeat the README
overview — go deeper here.]

## System diagram

```
[ASCII box-and-arrow diagram. Use consistent notation:
 → for data flow
 ──► for control flow / invocation
 ═══ for persistent connections
 Show every major component, every external dependency, and the direction of flow.]
```

## Components

[One subsection per major component. Read the actual source file for each one.]

### [Component Name]

- **Location**: `src/[path/to/file.ext]`
- **Purpose**: [What it does in one sentence — its responsibility boundary]
- **Inputs**: [What data or events it receives, and from where]
- **Outputs**: [What it produces, writes, or emits — and where that goes]
- **Key types/interfaces**: [The main struct, class, or interface that defines its contract]
- **Design notes**: [Non-obvious implementation choices — omit this field if there are none]

[Repeat for each major component. Include internal services, not just entry points.]

## Data model

[If the project has a persistent data model (database tables, document schemas, event
 schemas), describe it here. Show the entities, their key fields, and relationships.]

```
[Entity-relationship diagram in ASCII, or a table per entity with its fields]
```

[If there is no persistent data model (stateless service, CLI tool), omit this section.]

## Design decisions

[Each decision should have: the choice made, the alternatives that were considered, and
 the reason this was better for this project's constraints.]

1. **[Decision title]**

   *Choice*: [What was decided]
   *Alternatives considered*: [What else was evaluated]
   *Rationale*: [Why this was better — the specific constraint or goal it addressed]

2. **[Decision title]**

   [Same format]

[Include 3–6 decisions. Prioritise decisions that are non-obvious or that a future
 maintainer might question and want to reverse. Do not document decisions where the
 answer is "it's standard practice" — only document surprising or project-specific ones.]

## External dependencies

| Dependency | Version | Purpose | Alternatives considered |
|---|---|---|---|
| [library] | [version] | [what it does for the project] | [what else was evaluated] |

[Only include non-trivial dependencies — not standard library packages. Include the
 "Alternatives considered" column only if there is a meaningful story to tell.]

<!-- generated-by: project-docs-skill -->
