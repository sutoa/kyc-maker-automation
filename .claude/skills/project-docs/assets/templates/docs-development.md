# Development Guide

## Project structure

```
[Directory tree, 2–3 levels deep. Add a one-line comment per significant directory
 or file — not every file, just the ones a new contributor needs to know about.]
[project-root]/
├── [dir]/          # [one-line purpose]
│   ├── [file]      # [what it does]
│   └── [file]      # [what it does]
└── [dir]/          # [one-line purpose]
```

## Local setup

[Steps beyond the Quick Start — anything needed for a full development environment
 that is not needed to just run the app. Cover:
 - How to set up a local database or dependent services (Docker Compose if it exists)
 - Pre-commit hooks or git configuration
 - IDE-specific setup (if the project has .editorconfig, .vscode/, or similar)
 - How to reset the local environment from scratch]

```
[commands in order]
```

## Running tests

```
# Unit tests
[command]

# Integration tests (may need services running)
[command]

# Run a single test / test file
[command with example]

# With coverage
[command]
```

[Note any tests that require external services and how to skip them locally.]

## Linting and formatting

```
# Check
[lint command]

# Auto-fix / format
[format command]
```

[Note: "CI enforces linting — run this before pushing to avoid a failed build." if true.]

## Making changes

[Describe where to add each type of new contribution — the primary extension points.]

### Adding a new [route / agent / command / module]

[Step-by-step instructions, 5–10 lines. Be concrete about file locations and naming
 conventions. Example for a REST API: "1. Add a new route file to src/api/routes/.
 2. Register it in main.py with router.include_router(). 3. Add corresponding service
 method in src/services/. 4. Write a contract test in tests/contract/."]

### Adding a new [other common extension point]

[Same format. Include at least 2 extension points if the project has them.]

## Useful commands

| Command | What it does |
|---|---|
| `[command]` | [description] |
| `[command]` | [description] |

[Collect any commands that are commonly needed but not obvious — database reset, cache clear,
 log tailing, migration generation, seed data loading, etc.]

## Debugging tips

[2–5 tips specific to this codebase:
 - How to enable verbose/debug logging
 - Common errors and their causes
 - Where logs are written
 - How to inspect the database in development
 - Any known gotchas that trip up new contributors]

<!-- generated-by: project-docs-skill -->
