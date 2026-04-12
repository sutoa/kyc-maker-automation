"""Generic agent factory — builds agent callables from agents.yaml config.

All agent config (model, temperature, max_tokens, retry, prompts, output schemas)
comes from YAML. No hardcoded values.

Public API:
    build_agent_fn(agent_name, agent_cfg, agents_dir) -> Callable[[WorkflowState], WorkflowState]
"""

import importlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from pydantic import BaseModel

from src.core.state import WorkflowState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM provider factory
# ---------------------------------------------------------------------------


def _build_chat_model(model_string: str, temperature: float, max_tokens: int) -> Any:
    """Instantiate a LangChain ChatModel from a provider/model-name string."""
    provider, model_name = model_string.split("/", 1)
    if provider == "openai":
        return ChatOpenAI(model=model_name, temperature=temperature, max_tokens=max_tokens)
    elif provider in ("gemini", "google"):
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature, max_tokens=max_tokens)
    raise ValueError(
        f"Unsupported provider: '{provider}' in model string '{model_string}'. "
        "Expected 'openai/<model>' or 'gemini/<model>'."
    )


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
    """Replace {{key}} placeholders with values from context.

    Missing / None values render as empty string so placeholders
    disappear cleanly on the first pass (e.g. extractor_critic_feedback).
    """
    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        value = context.get(key)
        if value is None:
            return ""
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)

    return re.sub(r"\{\{(\w+)\}\}", replacer, template)


def _build_system_message(agent_cfg: dict[str, Any], prompt_content: str) -> str:
    """Compose system message: identity preamble + prompt content."""
    parts = []
    role = agent_cfg.get("role", "")
    goal = agent_cfg.get("goal", "")
    backstory = agent_cfg.get("backstory", "").strip()
    if role:
        parts.append(f"You are: {role}")
    if goal:
        parts.append(f"Your goal: {goal}")
    if backstory:
        parts.append(f"Background: {backstory}")
    if parts:
        parts.append("")
    parts.append(prompt_content)
    return "\n".join(parts)


def _extract_input_context(state: WorkflowState, input_keys: list[str]) -> dict[str, Any]:
    """Extract declared input_keys from state into a context dict."""
    return {key: state.get(key) for key in input_keys}


# ---------------------------------------------------------------------------
# LLM agent builder
# ---------------------------------------------------------------------------


def _build_llm_agent_fn(
    agent_name: str,
    agent_cfg: dict[str, Any],
    agents_dir: Path,
) -> Callable[[WorkflowState], WorkflowState]:
    """Build an LLM-backed agent function from config."""

    prompt_template = _load_prompt(agent_cfg["system_prompt"], agents_dir)
    output_schema_cfg = agent_cfg.get("output_schema")
    input_keys = agent_cfg.get("input_keys", [])
    output_key = agent_cfg["output_key"]
    model_string = agent_cfg["model"]
    temperature = float(agent_cfg.get("temperature", 0))
    max_tokens = int(agent_cfg.get("max_tokens", 4096))

    # Resolve schema once at build time (fail fast)
    schema_cls: type[BaseModel] | None = None
    is_list = False
    if output_schema_cfg:
        schema_cls = _resolve_schema(output_schema_cfg)
        is_list = bool(output_schema_cfg.get("is_list", False))

    def agent_fn(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        logger.info(f"[{workflow_id}] {agent_name}: starting (llm)")

        context = _extract_input_context(state, input_keys)
        rendered_prompt = _render_prompt(prompt_template, context)
        system_content = _build_system_message(agent_cfg, rendered_prompt)
        messages = [SystemMessage(content=system_content)]

        llm = _build_chat_model(model_string, temperature, max_tokens)

        if schema_cls is not None:
            if is_list:
                # Wrap in container so the LLM returns a list via JSON schema
                container_cls = type(
                    f"_{schema_cls.__name__}List",
                    (BaseModel,),
                    {"__annotations__": {"items": list[schema_cls]}},
                )
                structured_llm = llm.with_structured_output(container_cls, method="json_schema")
                raw = structured_llm.invoke(messages)
                result = raw.items
            else:
                structured_llm = llm.with_structured_output(schema_cls, method="json_schema")
                result = structured_llm.invoke(messages)
        else:
            # No schema — return raw string (e.g. formatter markdown output)
            result = llm.invoke(messages).content

        logger.info(f"[{workflow_id}] {agent_name}: completed")
        return WorkflowState(**{**state, output_key: result})

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

    def agent_fn(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        logger.info(f"[{workflow_id}] {agent_name}: starting (rule)")
        result = rule_fn(state)
        logger.info(f"[{workflow_id}] {agent_name}: completed")
        return WorkflowState(**{**state, output_key: result})

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

    Args:
        agent_name: The agent key (used for logging).
        agent_cfg:  Effective merged config (defaults already applied).
        agents_dir: Directory of agents.yaml (resolves relative prompt paths).

    Returns:
        A callable (state: WorkflowState) -> WorkflowState ready for LangGraph.
    """
    execution = agent_cfg.get("execution", "llm")
    if execution == "llm":
        return _build_llm_agent_fn(agent_name, agent_cfg, agents_dir)
    elif execution == "rule":
        return _build_rule_agent_fn(agent_name, agent_cfg)
    raise ValueError(
        f"Agent '{agent_name}' has unsupported execution type '{execution}'. "
        "Expected 'llm' or 'rule'."
    )
