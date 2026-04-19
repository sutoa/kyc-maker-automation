# ADR 001: LangGraph Routing Pattern for Critic-Retry Loops

**Date:** 2026-04-19  
**Status:** Accepted

## Context

Each LLM agent in the workflow has a corresponding critic agent that validates its output. When the critic finds issues, the workflow must retry the agent (up to a max) while incrementing a retry counter. When the critic passes, the workflow advances to the next agent.

This requires **conditional routing + state update in one step** — something `add_conditional_edges` alone cannot do, because LangGraph routing functions passed to `add_conditional_edges` are only allowed to return a string (the route key); they cannot update state.

## Decision

Use a **dedicated router node** (type: router in YAML) after each critic, returning a LangGraph `Command` object that combines routing and state update atomically.

### Graph topology

```
agent ──(unconditional)──► critic ──(unconditional)──► critic_router ──(Command)──► agent (retry)
                                                                                  ├──────────────► next_agent (pass)
                                                                                  └──────────────► END (fail_max)
```

### Responsibilities

| Node | Type | Responsibility |
|------|------|----------------|
| `extractor` | LLM agent (factory-built) | Extract persons, write `extracted_persons` |
| `critic_1` | LLM agent (factory-built) | Validate output, write `extractor_critic_feedback` (single output key) |
| `extractor_critic_router` | router (pure Python) | Read feedback, return `Command(goto=..., update={"retry_count": ...})` |

### Edge declaration (workflows.yaml)

```yaml
- from: extractor
  to: critic_1                    # unconditional

- from: critic_1
  to: extractor_critic_router     # unconditional

# NO edge from extractor_critic_router — Command.goto IS the edge at runtime
```

### Router node implementation

```python
def route_on_extractor_critic_decision(state) -> Command[Literal["extractor", "next_agent", END]]:
    feedback = state.get("extractor_critic_feedback")
    retry_count = state.get("extraction_retry_count", 0) or 0

    if feedback is None or feedback.status == "pass":
        return Command(goto="next_agent")

    if retry_count >= MAX_RETRIES:
        return Command(goto=END)

    return Command(goto="extractor", update={"extraction_retry_count": retry_count + 1})
```

## LLM Node vs Router Node

| | LLM Node | Router Node |
|---|---|---|
| **Built by** | Agent factory | Plain Python function |
| **Returns** | Full `WorkflowState` dict | `Command(goto=..., update={...})` |
| **State update** | Yes — LangGraph merges the returned dict via reducers | Yes — but only the keys declared in `Command.update` |
| **Routing** | No — outbound edges declared in YAML | Yes — `Command.goto` determines next node at runtime; no YAML edges needed |
| **LLM call** | Yes | No |
| **Output keys** | One `output_key` per agent (enforced by factory) | Any keys needed for graph-level bookkeeping (e.g. retry counters) |
| **When to use** | Doing work: extraction, validation, classification | Deciding where to go next, especially when a state update is needed alongside the routing decision |

### Why LLM nodes cannot replace router nodes here

An LLM node could increment the retry counter — but it cannot control routing. It always follows the edges declared in YAML. A router node returning `Command` is the only way to both update state and dynamically choose the next node in a single step.

### Why routing functions (add_conditional_edges) cannot replace router nodes here

A routing function passed to `add_conditional_edges` can only return a string. LangGraph does not process state updates from routing functions — any direct dict mutation is an unsupported side effect that bypasses the reducer system and breaks checkpointing.

## Rationale

- **`add_conditional_edges` cannot update state** — per LangGraph docs: *"If you only need to route without updating state, use conditional edges instead."* The inverse is also true: when you need state update + routing, use `Command`.
- **Critic LLM agents write a single output key** — the agent factory is generic and maps one `output_key` per agent. Retry count is a graph-level concern, not an LLM output field.
- **`Command` is atomic** — state update and routing happen in the same step, preventing any race or inconsistency between the counter and the routing decision.

## Consequences

- Each critic phase requires three YAML nodes: `agent`, `critic`, `critic_router`
- Router nodes are pure Python functions, not LLM agents — no factory involvement
- `Command.goto` targets must be declared as return type annotations (`Literal[...]`) for LangGraph graph rendering to work correctly
