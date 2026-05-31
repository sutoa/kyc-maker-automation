---
name: project-docs
description: >
  Generate production-quality project documentation for any codebase — README,
  architecture docs, component reference, data-flow, configuration, development guide,
  and function-level implementation deep-dives.
  Use this skill whenever the user wants to document a project, create or improve a README,
  write getting-started guides, explain a codebase to new contributors, produce architecture
  documentation, onboard developers, or says anything like "document this project", "write
  docs", "create a README", "help someone understand this codebase", "generate project docs",
  "write documentation", or "explain how [function] works internally". Also trigger when
  the user has just built something new and hasn't documented it yet — don't wait to be
  explicitly asked.
---

# Project Documentation Generator

Produce documentation that matches real-world best practices from projects like FastAPI,
React, LangChain, Docker Compose, Spring Boot, and Tokio. Before writing anything, detect
the project type and select the right documentation archetype — then generate content from
the actual codebase, never from placeholders.

Templates for each output file live in `assets/templates/`. Read the relevant template
before generating each file — the template is your contract for structure and content depth.

---

## Generation Marker and Overwrite Policy

Every file this skill creates must end with this exact HTML comment on its own line:

```
<!-- generated-by: project-docs-skill -->
```

This comment is invisible when rendered and acts as a fingerprint.

**Before writing any file**, check whether it already exists:
- File exists and contains `<!-- generated-by: project-docs-skill -->` → overwrite silently
- File exists and does NOT contain that marker → ask the user: *"[filename] already exists and appears to be hand-written. Replace it, or write to [filename.generated.md] alongside it?"*
- File does not exist → create it

---

## Phase 1: Detect

Read these files in parallel (skip any that don't exist):

**Tech stack** — the first match wins:

| File | Stack |
|---|---|
| `package.json` | JavaScript / TypeScript |
| `pom.xml` or `build.gradle` or `build.gradle.kts` | Java / Kotlin |
| `setup.py`, `pyproject.toml`, or `requirements.txt` | Python |
| `go.mod` | Go |
| `Cargo.toml` | Rust |
| `*.csproj` or `*.sln` | C# / .NET |

**Docs site signals** — check for any of:
`mkdocs.yml`, `docusaurus.config.js`, `antora-playbook.yml`, `.readthedocs.yaml`, `vitepress.config.js`

**Contributor-repo signals** — check for:
`CONTRIBUTING.md` AND (`Makefile` OR `.github/workflows/` with >2 workflow files OR a `scripts/` directory with build scripts)

**Project size** — run:
```bash
find src -maxdepth 4 -type d 2>/dev/null | head -30
```
Count top-level source directories to gauge complexity.

Also read the main entry point and 2–3 representative source files to understand what the project actually does.

---

## Phase 2: Select Archetype

State your selection as a single line before generating, e.g.:
> *Archetype: **Full Onboarding** — Python service with 6 major components, no external docs site detected.*

| Condition | Archetype |
|---|---|
| External docs site detected | **Gateway** |
| Strong contributor-repo signals | **Contributor Ops** |
| Framework / library competing for adoption; DX is the selling point | **Full Onboarding** |
| Service, application, CLI tool, or unclear | **Full Onboarding** |

When in doubt, default to **Full Onboarding** — it is the most useful for a newcomer.

---

## Phase 3: Generate README

### Badge row by language

**Language-version badges — always include.** Extract the version from the manifest file;
do not skip because the package is not yet published:

- **Python**: `requires-python` in pyproject.toml → `.python-version` → `runtime.txt` → infer from `requirements.txt` comments or tooling pins
- **Go**: the `go X.YY` line at the top of `go.mod`
- **Node.js**: `engines.node` in `package.json`
- **Java/Kotlin**: `<java.version>` or `<maven.compiler.source>` in `pom.xml`; `sourceCompatibility` in `build.gradle`
- **Rust**: `edition` in `Cargo.toml`

**CI badge** — include if `.github/workflows/` has any `.yml` files. Use the first workflow file found.

**Registry badges** (PyPI, npm, crates.io, Maven Central) — only include if the package appears ready to publish: a non-placeholder version (`"1.2.3"`, not `"0.0.0"` or `"SNAPSHOT"`) and a package name that doesn't look like a template (`example`, `test`, `internal`).

**License badge** — always include if a `LICENSE` file exists.

| Language | Badge set |
|---|---|
| Python | CI · Python version · PyPI version (if published) · license |
| JavaScript / TypeScript | CI · Node version · npm version (if published) · license |
| Go | CI · Go version · Go Report Card · license |
| Rust | CI · Rust edition · crates.io version (if published) · license |
| Java / Kotlin | CI · Java version · Maven Central (if published) · license |
| C# / .NET | CI · .NET version · NuGet (if published) · license |
| Unknown | CI · license |

### Generating the README

Read the appropriate template from `assets/templates/`:
- `readme-gateway.md` → for Gateway archetype
- `readme-full-onboarding.md` → for Full Onboarding archetype
- `readme-contributor-ops.md` → for Contributor Ops archetype

Fill every section in the template from the actual codebase. Do not leave any section
at its template description — every bracket placeholder must be replaced with real content.

**Target length**: 250–400 lines for Full Onboarding on a project with 4+ components.
A thin README signals an incomplete onboarding experience.

---

## Phase 4: Generate docs/ Directory

Generate a `docs/` directory when the project has **5 or more major components** OR **2 or
more distinct user-facing workflows**. Check for these using what you found in Phase 1.

Apply the overwrite policy to each file individually.

For each docs/ file, read the corresponding template from `assets/templates/` before writing:

| File to create | Template to read | Create when |
|---|---|---|
| `docs/getting-started.md` | (no template — derive from README Quick Start, expand) | Always |
| `docs/architecture.md` | `docs-architecture.md` | Always |
| `docs/data-flow.md` | `docs-data-flow.md` | Project has pipelines, queues, or multi-step request flows |
| `docs/configuration.md` | `docs-configuration.md` | Non-trivial config surface (>5 env vars or config file) |
| `docs/reference/[component].md` | (no template — adapt from readme-full-onboarding API Reference) | REST API or CLI with multiple commands |
| `docs/development.md` | `docs-development.md` | Always |

---

## Phase 5: Function Implementation Deep-Dives (optional)

After completing Phases 3–4, ask the user:

> *"Documentation is complete. Would you like me to generate implementation deep-dives for
> any specific functions or components? These cover: description, design decisions,
> complexity and edge cases, a Mermaid sequence diagram, consumers, known issues, and
> future enhancements. If yes, list the function or component names."*

If the user provides names:

1. For each named function or component:
   a. Read `assets/templates/function-deep-dive.md`
   b. Find the function in the codebase — read its source file fully, then read its test file if one exists
   c. Trace all callers: `grep -r "function_name"` across the source tree
   d. Fill every section of the template with real findings from the code
   e. The **Sequence diagram** section must always use a Mermaid `sequenceDiagram` block —
      not ASCII art. Trace the full call chain from the external caller down to every
      dependency (database, LLM, external service) and back, including alt/opt blocks
      for error paths.

2. Save all deep-dives to a single file: `docs/deep-dive.md`
   - If the file does not exist yet, create it with a top-level heading and the first deep-dive.
   - If it already exists and was generated by this skill, append each new deep-dive as a
     new `## [Function / Component Name]` section.
   - Apply the overwrite policy to the file as a whole.

3. Update `docs/development.md` to link to `docs/deep-dive.md` if it was just created.

**What makes a good deep-dive**: The value is in the sections the code cannot tell you —
design decisions, the "why not X", the edge cases not yet handled, the future directions.
Read the function carefully before writing. If something is genuinely simple and
well-named, say so plainly — do not invent complexity.

---

## Quality checks before finishing

Before reporting the task complete:
- [ ] Every generated file ends with `<!-- generated-by: project-docs-skill -->`
- [ ] No section contains placeholders — all content is from the actual codebase
- [ ] Architecture diagram uses real component names from the code
- [ ] Install commands match the actual tech stack (not generic `pip install`)
- [ ] Configuration table covers every variable found in `.env.example`, `config.yaml`, or equivalent
- [ ] Language-version badge is present (extracted from manifest — never skipped for being unpublished)
- [ ] README is 250+ lines for projects with 4+ components (`wc -l README.md`)
- [ ] "Key design decisions" lists real decisions from the codebase, not generic statements
- [ ] API Reference / Command Reference section is present for projects with multiple commands, endpoints, or selectable components
- [ ] Phase 5 prompt was offered to the user
