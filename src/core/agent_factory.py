"""Generic agent factory — builds agent callables from agents.yaml config.

This is the single place where YAML config is translated into executable
agent functions. No agent names, model names, prompt paths, retry counts,
or state keys are hardcoded here or in callers — all come from config.

Public API:
    build_agent_fn(agent_name, agent_cfg, agents_dir) -> Callable[[WorkflowState], WorkflowState]
"""

import asyncio
import importlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel

from src.core.state import WorkflowState
from src.models.enums import CriticDecision
from src.models.workflow import CriticFeedback

logger = logging.getLogger(__name__)


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
    """Replace {{key}} placeholders in template with values from context.

    Missing / None values are replaced with empty string so the
    placeholder disappears cleanly.
    """
    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        value = context.get(key)
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)

    return re.sub(r"\{\{(\w+)\}\}", replacer, template)


def _build_system_message(agent_cfg: dict[str, Any], prompt_content: str) -> str:
    """Compose system message: identity preamble + prompt content."""
    role = agent_cfg.get("role", "")
    goal = agent_cfg.get("goal", "")
    backstory = agent_cfg.get("backstory", "").strip()

    parts = []
    if role:
        parts.append(f"You are: {role}")
    if goal:
        parts.append(f"Your goal: {goal}")
    if backstory:
        parts.append(f"Background: {backstory}")
    if parts:
        parts.append("")  # blank line separator

    parts.append(prompt_content)
    return "\n".join(parts)


def _extract_input_context(state: WorkflowState, input_keys: list[str]) -> dict[str, Any]:
    """Extract the declared input_keys from state into a context dict."""
    return {key: state.get(key) for key in input_keys}


def _parse_llm_response(
    response_content: str,
    schema_cls: type[BaseModel],
    is_list: bool,
) -> Any:
    """Parse LLM response text into the declared output schema.

    Handles JSON wrapped in markdown code blocks.
    """
    text = response_content.strip()

    # Strip markdown code fences
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        text = text[start:end].strip()

    data = json.loads(text)

    if is_list:
        # Support both bare array and {"key": [...]} wrapper
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Take the first list value found
            items = next((v for v in data.values() if isinstance(v, list)), [])
        else:
            raise ValueError(f"Expected list response, got {type(data)}")
        return [schema_cls(**item) if isinstance(item, dict) else item for item in items]
    else:
        if isinstance(data, dict):
            return schema_cls(**data)
        raise ValueError(f"Expected dict response for single object, got {type(data)}")


def _check_and_enforce_max_attempts(
    state: WorkflowState,
    agent_cfg: dict[str, Any],
    retry_count_key: str | None,
) -> bool:
    """Return True if max retry attempts have been reached.

    Compares the current retry count in state against retry.max_attempts
    from agent config.
    """
    if not retry_count_key:
        return False
    max_attempts = int(agent_cfg.get("retry", {}).get("max_attempts", 4))
    current = state.get(retry_count_key, 0) or 0
    return current >= max_attempts


def _increment_retry_count(state: WorkflowState, retry_count_key: str) -> WorkflowState:
    """Return a new state with retry_count_key incremented by 1."""
    current = state.get(retry_count_key, 0) or 0
    return WorkflowState(**{**state, retry_count_key: current + 1})


def _make_fail_max_feedback(agent_name: str, retry_count_key: str | None, state: WorkflowState) -> CriticFeedback:
    """Build a FAIL_MAX CriticFeedback for when max attempts are exceeded."""
    count = state.get(retry_count_key, 0) if retry_count_key else 0
    return CriticFeedback(
        id=str(uuid4()),
        agent_execution_id=str(uuid4()),
        critic_agent_name=agent_name,
        decision=CriticDecision.FAIL_MAX,
        suggested_corrections=f"Maximum retry attempts ({count}) exceeded.",
        created_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# LLM agent builder
# ---------------------------------------------------------------------------


def _build_llm_agent_fn(
    agent_name: str,
    agent_cfg: dict[str, Any],
    agents_dir: Path,
) -> Callable[[WorkflowState], WorkflowState]:
    """Build an LLM-backed agent function from config."""

    # Resolve everything at build time (fail fast, not at runtime)
    prompt_template = _load_prompt(agent_cfg["system_prompt"], agents_dir)
    output_schema_cfg = agent_cfg["output_schema"]
    schema_cls = _resolve_schema(output_schema_cfg)
    is_list = bool(output_schema_cfg.get("is_list", False))
    input_keys = agent_cfg.get("input_keys", [])
    output_key = agent_cfg["output_key"]
    retry_count_key = agent_cfg.get("retry_count_key")
    model_string = agent_cfg["model"]
    temperature = float(agent_cfg["temperature"])
    max_tokens = int(agent_cfg["max_tokens"])
    retry_cfg = agent_cfg.get("retry", {})
    is_critic_output = issubclass(schema_cls, CriticFeedback)

    def agent_fn(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        logger.info(f"[{workflow_id}] {agent_name}: starting (llm)")

        # If this is a critic and max attempts exceeded, return FAIL_MAX immediately
        if is_critic_output and _check_and_enforce_max_attempts(state, agent_cfg, retry_count_key):
            feedback = _make_fail_max_feedback(agent_name, retry_count_key, state)
            logger.info(f"[{workflow_id}] {agent_name}: max attempts exceeded → FAIL_MAX")
            return WorkflowState(**{**state, output_key: feedback})

        # Increment retry count if previous critic said FAIL_RETRY and this agent has a retry key
        current_state = state
        if retry_count_key:
            last_feedback = state.get("last_critic_feedback")
            last_decision = getattr(last_feedback, "decision", None) if last_feedback else None
            if last_decision == CriticDecision.FAIL_RETRY:
                current_state = _increment_retry_count(state, retry_count_key)
                logger.info(
                    f"[{workflow_id}] {agent_name}: retry #{current_state.get(retry_count_key)}"
                )

        # Build context from input_keys and render prompt
        context = _extract_input_context(current_state, input_keys)
        rendered_prompt = _render_prompt(prompt_template, context)
        system_content = _build_system_message(agent_cfg, rendered_prompt)

        # Import LLM tooling here to avoid circular imports
        from src.core.llm import get_llm_provider
        from src.core.llm.base import Message, MessageRole

        llm = get_llm_provider(model_string, retry_cfg)

        # Run async LLM call in sync context
        async def _call():
            return await llm.complete(
                messages=[Message(role=MessageRole.SYSTEM, content=system_content)],
                temperature=temperature,
                max_tokens=max_tokens,
            )

        try:
            response = asyncio.get_event_loop().run_until_complete(_call())
        except RuntimeError:
            # Already in an event loop (e.g. during async workflow execution)
            loop = asyncio.new_event_loop()
            try:
                response = loop.run_until_complete(_call())
            finally:
                loop.close()

        logger.info(f"[{workflow_id}] {agent_name}: LLM responded, parsing output")

        result = _parse_llm_response(response.content, schema_cls, is_list)
        return WorkflowState(**{**current_state, output_key: result})

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
    retry_count_key = agent_cfg.get("retry_count_key")
    max_attempts = int(agent_cfg.get("retry", {}).get("max_attempts", 4))
    output_schema_cfg = agent_cfg["output_schema"]
    is_critic_output = output_schema_cfg.get("ref", "").endswith("CriticFeedback")

    def agent_fn(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        logger.info(f"[{workflow_id}] {agent_name}: starting (rule)")

        # Enforce max attempts for rule-based critics
        if is_critic_output and retry_count_key:
            current_count = state.get(retry_count_key, 0) or 0
            if current_count >= max_attempts:
                feedback = _make_fail_max_feedback(agent_name, retry_count_key, state)
                logger.info(f"[{workflow_id}] {agent_name}: max attempts exceeded → FAIL_MAX")
                return WorkflowState(**{**state, output_key: feedback})

        # Call the rule function — expected signature: (state) -> CriticFeedback
        result: CriticFeedback = rule_fn(state)

        # Increment retry count if result is FAIL_RETRY
        current_state = state
        if retry_count_key and isinstance(result, CriticFeedback):
            if result.decision == CriticDecision.FAIL_RETRY:
                current_state = _increment_retry_count(state, retry_count_key)
                logger.info(
                    f"[{workflow_id}] {agent_name}: FAIL_RETRY, "
                    f"retry count now {current_state.get(retry_count_key)}"
                )

        logger.info(
            f"[{workflow_id}] {agent_name}: decision="
            f"{getattr(result, 'decision', 'unknown')}"
        )
        return WorkflowState(**{**current_state, output_key: result})

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

    Reads all configuration from agent_cfg — no hardcoded values.
    Dispatches on execution: llm | rule.

    Args:
        agent_name: The agent key (used for logging).
        agent_cfg: Effective merged config for this agent (defaults already applied).
        agents_dir: Directory of agents.yaml, used to resolve relative prompt paths.

    Returns:
        A callable (state: WorkflowState) -> WorkflowState ready for LangGraph.

    Raises:
        ValueError: If config is missing required fields or references are invalid.
        FileNotFoundError: If system_prompt.file does not exist.
    """
    execution = agent_cfg.get("execution", "llm")

    if execution == "llm":
        return _build_llm_agent_fn(agent_name, agent_cfg, agents_dir)
    elif execution == "rule":
        return _build_rule_agent_fn(agent_name, agent_cfg)
    else:
        raise ValueError(
            f"Agent '{agent_name}' has unsupported execution type '{execution}'. "
            "Expected 'llm' or 'rule'."
        )
