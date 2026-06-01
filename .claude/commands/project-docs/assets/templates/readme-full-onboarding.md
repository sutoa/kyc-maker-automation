# [Project Name]
[badge row]

> [Tagline — one sentence: what it does and who it is for]

[Overview: 3–5 sentences. Cover the problem, the approach, and what sets this apart from
 alternatives. Name the actual mechanisms — "uses sliding-window counters in Redis" is
 better than "efficient rate limiting". A reader who has never heard of this project should
 understand what it does and why they'd use it after reading this paragraph.]

## Features

- [Concrete capability — name the mechanism, not just the benefit]
- [Concrete capability]
[5–10 bullets drawn from what the code actually does. Read the source to find the right
 level of specificity — "Async email notifications via Celery workers with configurable
 retry backoff" is better than "Email notifications".]

## Requirements

- [Runtime + minimum version, e.g. Python 3.11+, Java 17+, Node 20+]
- [External services or system dependencies, e.g. PostgreSQL 15, Redis 7, git-filter-repo]
[Only list what is actually required for the project to run.]

## Installation

[Install command — exact package manager and package name]

[If env config is needed:]
```
cp .env.example .env
```
Required variables to set immediately:
- `VAR_1` — [what it does]
- `VAR_2` — [what it does]
[Only list the ones that will cause the app to fail if left at default.]

[If a migration, build, or seed step is needed before first run:]
```
[migration or build command]
```

[Startup command:]
```
[run command]
```

## Quick Start

[Show the most common real-world usage with real values — no [PLACEHOLDER] text.
 For CLIs: show the primary command with annotated terminal output.
 For REST APIs: authentication + at least two resource requests with the JSON response.
 For libraries with multiple components: one complete, copy-pasteable code block per major
 variant. A reader must be able to run each example without guessing or looking at source.]

### [Step 1 title, e.g. "Authenticate"]

```[language]
[actual code or curl command]
```

Expected response:
```json
[actual response shape from the code]
```

### [Step 2 title, e.g. "Create a resource"]

```[language]
[actual code or curl command]
```

[Add more steps for each distinct workflow or major feature variant. Do not collapse
 unrelated features into one block — keep them separate so each stands alone.]

## [API Reference / Command Reference / Usage]

[Include this section whenever the project has multiple commands, endpoints, or selectable
 components. This section saves every new user from reading source code. Omit only for
 trivial single-purpose tools.]

[For CLI tools — one row per subcommand:]
| Command | Key flags | Description |
|---|---|---|
| `[binary] [subcommand]` | `--flag value` | [what it does] |

[Global flags that apply to all subcommands, if any:]
| Flag | Type | Default | Description |
|---|---|---|---|
| `--flag` | string | — | [what it controls] |

[For libraries with multiple components — one subsection per major component:]

### [Component / Algorithm / Strategy Name]

[One sentence: when to pick this over the alternatives]

```[language]
// Complete, runnable example — not a fragment
[actual code]
```

[If this component has configuration options, show a table:]
| Option | Type | Default | Description |
|---|---|---|---|
| `option` | type | default | [what it controls] |

[For REST APIs — endpoint table:]
| Method | Path | Auth required | Description |
|---|---|---|---|
| `POST` | `/auth/login` | No | Obtain a JWT |
| `GET` | `/resource` | Bearer token | [description] |
| `POST` | `/resource` | Bearer token | [description] |
| `PUT` | `/resource/:id` | Bearer + [role] | [description] |
| `DELETE` | `/resource/:id` | Bearer + [role] | [description] |

[For REST APIs, also show request/response shapes for the most important endpoints:]
**Create resource request:**
```json
{
  "[field]": "[type and description]"
}
```

## Architecture

[DECISION: Is docs/architecture.md being generated alongside this README in Phase 4?

IF YES (docs/ is being generated):
  Write 2–3 sentences naming the primary layers and the data flow between them. Name the
  pipeline stages in one line. Then add two links — don't repeat what the dedicated docs
  already contain:
  
  - Component breakdown, data model, and design decisions → [docs/architecture.md](docs/architecture.md)
  - Request lifecycle and sequence diagrams → [docs/data-flow.md](docs/data-flow.md)
  
  Do NOT include a component table or design decisions in the README — those live in
  docs/architecture.md. Repetition forces readers to track which version is canonical.

IF NO (no docs/ directory being generated):
  Write a full architecture section:
  - 1–2 paragraph narrative covering primary layers and core structural decisions
  - ASCII box-and-arrow diagram showing major components and data flow
  - Component table (one row per major component with location and purpose)
  - Key design decisions: 2–4 non-obvious choices visible from the code structure
]

## Configuration

[DECISION: Is docs/configuration.md being generated alongside this README in Phase 4?

IF YES (docs/ is being generated):
  List ONLY the variables that will cause immediate startup failure if not set (no safe default).
  For everything else, link to the dedicated configuration doc:
  
  Required before first run:
  | Variable | When required |
  |---|---|
  | `REQUIRED_VAR` | [condition] |
  
  Full reference (all variables with defaults and valid values) → [docs/configuration.md](docs/configuration.md)
  Agent-level overrides (model, temperature, retry policy) → [relevant config file]
  
  Do NOT repeat the full variable table — it belongs in docs/configuration.md.

IF NO (no docs/ directory being generated):
  Show the full variable table covering every variable found in .env.example, config.py,
  application.properties, or equivalent. Group by concern (LLM provider, database, etc.)
  Include a "Required" column. If a structured YAML/TOML config exists, show an annotated
  example of the key fields.
]

## Documentation

[Link to ./docs/ if generated. Omit this section if no docs/ directory was created.
 Include every docs/ file that was generated. Always put getting-started.md first.]

- [docs/getting-started.md](docs/getting-started.md) — step-by-step setup with error troubleshooting
- [docs/architecture.md](docs/architecture.md) — component breakdown, data model, design decisions
- [docs/data-flow.md](docs/data-flow.md) — request lifecycle and Mermaid sequence diagrams
- [docs/configuration.md](docs/configuration.md) — full env var reference and config file examples
- [docs/development.md](docs/development.md) — local setup, testing, and extension guide
- [docs/deep-dive.md](docs/deep-dive.md) — implementation deep-dives (add if Phase 5 was run)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) or open an issue.

## License

[License name]. See [LICENSE](LICENSE).

<!-- generated-by: project-docs-skill -->
