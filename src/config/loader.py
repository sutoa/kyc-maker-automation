"""Configuration loader for AGENTFLOW v1.2 YAML specification.

Loads and validates:
- agents.yaml  — agent library (role, goal, backstory, input_keys, output_key, …)
- workflows.yaml — workflow topology (nodes, edges, state schema, runtime, …)

Validation uses JSON Schema for structural checks plus semantic
cross-validation (e.g. every node references a known agent key).
"""

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


class ConfigValidationError(ConfigError):
    """Raised when configuration validation fails."""

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = errors or []


# Default paths relative to this module
_CONFIG_DIR = Path(__file__).parent
_SCHEMA_DIR = _CONFIG_DIR / "schemas"
_AGENTS_FILE = _CONFIG_DIR / "agents.yaml"
_WORKFLOWS_FILE = _CONFIG_DIR / "workflows.yaml"
_AGENT_SCHEMA_FILE = _SCHEMA_DIR / "agent.schema.json"
_WORKFLOW_SCHEMA_FILE = _SCHEMA_DIR / "workflow.schema.json"


# ---------------------------------------------------------------------------
# Low-level I/O helpers
# ---------------------------------------------------------------------------


def load_yaml(file_path: Path) -> dict[str, Any]:
    """Load a YAML file.

    Args:
        file_path: Path to the YAML file.

    Returns:
        Parsed YAML content as dictionary.

    Raises:
        ConfigError: If file cannot be loaded or parsed.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError(f"Configuration file not found: {file_path}")
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {file_path}: {e}")


def load_json_schema(file_path: Path) -> dict[str, Any]:
    """Load a JSON schema file.

    Args:
        file_path: Path to the JSON schema file.

    Returns:
        Parsed JSON schema as dictionary.

    Raises:
        ConfigError: If file cannot be loaded or parsed.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Schema file not found: {file_path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {file_path}: {e}")


def validate_against_schema(
    config: dict[str, Any],
    schema: dict[str, Any],
    config_name: str = "config",
) -> None:
    """Validate configuration against JSON schema.

    Args:
        config: Configuration dictionary to validate.
        schema: JSON schema to validate against.
        config_name: Name of config for error messages.

    Raises:
        ConfigValidationError: If validation fails.
    """
    try:
        import jsonschema
        from jsonschema import Draft7Validator
    except ImportError:
        logger.warning("jsonschema not installed, skipping schema validation")
        return

    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors(config))

    if errors:
        error_messages = []
        for error in errors:
            path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            error_messages.append({"path": path, "message": error.message})

        raise ConfigValidationError(
            f"Invalid {config_name}: {len(errors)} validation error(s)",
            errors=error_messages,
        )


# ---------------------------------------------------------------------------
# Agents config
# ---------------------------------------------------------------------------


def validate_agents_config(config: dict[str, Any]) -> None:
    """Validate agents configuration semantically (v1.2).

    Checks beyond JSON schema:
    - All required KYC agents are present
    - Each agent has exactly one of system_prompt.file or system_prompt.inline
    - Each agent has exactly one of output_schema.ref or output_schema.example

    Args:
        config: Agents configuration dictionary.

    Raises:
        ConfigValidationError: If semantic validation fails.
    """
    errors = []
    agents = config.get("agents", {})

    # Required agents are derived from workflow nodes that reference agents.
    # At pure agents.yaml validation time we only check that each defined agent
    # has valid structure. Cross-validation against workflow nodes happens in
    # validate_workflows_config().

    for name, agent in agents.items():
        execution = agent.get("execution", "llm")

        # LLM agents must have system_prompt
        if execution == "llm":
            sp = agent.get("system_prompt", {})
            if not isinstance(sp, dict) or ("file" not in sp and "inline" not in sp):
                errors.append({
                    "path": f"agents.{name}.system_prompt",
                    "message": "LLM agents must have system_prompt with 'file' or 'inline'",
                })
        # Rule agents must have rule_fn
        elif execution == "rule":
            if not agent.get("rule_fn"):
                errors.append({
                    "path": f"agents.{name}.rule_fn",
                    "message": "Rule agents must have 'rule_fn' (dotted Python path)",
                })

        # output_schema, if present, must have ref or example
        os_ = agent.get("output_schema")
        if os_ is not None:
            if not isinstance(os_, dict) or ("ref" not in os_ and "example" not in os_):
                errors.append({
                    "path": f"agents.{name}.output_schema",
                    "message": "Must have exactly one of 'ref' or 'example'",
                })

    if errors:
        raise ConfigValidationError(
            f"Agents config semantic validation failed: {len(errors)} error(s)",
            errors=errors,
        )


def load_agents_config(
    file_path: Path | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Load and validate agents configuration (v1.2).

    Args:
        file_path: Path to agents.yaml (default: bundled config).
        validate: Whether to validate against schema and semantics.

    Returns:
        Validated agents configuration dictionary.

    Raises:
        ConfigError: If loading fails.
        ConfigValidationError: If validation fails.
    """
    file_path = file_path or _AGENTS_FILE
    config = load_yaml(file_path)

    if validate:
        try:
            schema = load_json_schema(_AGENT_SCHEMA_FILE)
            validate_against_schema(config, schema, "agents")
        except ConfigError as e:
            logger.warning(f"Schema validation skipped: {e}")

        validate_agents_config(config)

    logger.info(f"Loaded agents config with {len(config.get('agents', {}))} agents")
    return config


# ---------------------------------------------------------------------------
# Workflows config
# ---------------------------------------------------------------------------


def validate_workflows_config(
    config: dict[str, Any],
    agents_config: dict[str, Any],
) -> None:
    """Validate workflows configuration semantically (v1.2).

    Checks beyond JSON schema:
    - workflow.entry_point resolves to a node in nodes
    - Every agent-type node references a key that exists in agents_config
    - Every edge target (to / condition.routes values) resolves to a valid node

    Args:
        config: Workflows configuration dictionary.
        agents_config: Agents configuration for cross-validation.

    Raises:
        ConfigValidationError: If semantic validation fails.
    """
    errors = []
    agents = agents_config.get("agents", {})
    nodes = config.get("nodes", {})
    edges = config.get("edges", [])
    workflow_meta = config.get("workflow", {})
    entry_point = workflow_meta.get("entry_point", "")

    valid_node_names = set(nodes.keys()) | {"__start__"}

    # entry_point must exist in nodes (or be __start__ which is a sentinel)
    if entry_point != "__start__" and entry_point not in nodes:
        errors.append({
            "path": "workflow.entry_point",
            "message": f"Entry point '{entry_point}' not found in nodes",
        })

    # Every agent-type node must reference a known agent
    for node_name, node_def in nodes.items():
        if node_def.get("type") == "agent":
            agent_key = node_def.get("agent")
            if agent_key and agent_key not in agents:
                errors.append({
                    "path": f"nodes.{node_name}.agent",
                    "message": f"Agent '{agent_key}' not found in agents config",
                })

    # Every edge target must resolve to a valid node
    for i, edge in enumerate(edges):
        from_node = edge.get("from", "")
        if from_node not in valid_node_names:
            errors.append({
                "path": f"edges[{i}].from",
                "message": f"Unknown source node '{from_node}'",
            })

        if "to" in edge:
            to_node = edge["to"]
            if to_node not in nodes:
                errors.append({
                    "path": f"edges[{i}].to",
                    "message": f"Unknown target node '{to_node}'",
                })

        if "condition" in edge:
            routes = edge["condition"].get("routes", {})
            for route_key, target in routes.items():
                if route_key == "default":
                    continue
                if target not in nodes:
                    errors.append({
                        "path": f"edges[{i}].condition.routes.{route_key}",
                        "message": f"Unknown target node '{target}'",
                    })

    if errors:
        raise ConfigValidationError(
            f"Workflows config semantic validation failed: {len(errors)} error(s)",
            errors=errors,
        )


def load_workflows_config(
    file_path: Path | None = None,
    agents_config: dict[str, Any] | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Load and validate workflows configuration (v1.2).

    Args:
        file_path: Path to workflows.yaml (default: bundled config).
        agents_config: Agents config for cross-validation (loaded if not provided).
        validate: Whether to validate semantics.

    Returns:
        Validated workflows configuration dictionary.

    Raises:
        ConfigError: If loading fails.
        ConfigValidationError: If validation fails.
    """
    file_path = file_path or _WORKFLOWS_FILE
    config = load_yaml(file_path)

    if validate:
        try:
            schema = load_json_schema(_WORKFLOW_SCHEMA_FILE)
            validate_against_schema(config, schema, "workflow")
        except ConfigError as e:
            logger.warning(f"Schema validation skipped: {e}")

        if agents_config is None:
            agents_config = load_agents_config(validate=False)

        validate_workflows_config(config, agents_config)

    workflow_id = config.get("workflow", {}).get("id", "unknown")
    node_count = len(config.get("nodes", {}))
    edge_count = len(config.get("edges", []))
    logger.info(
        f"Loaded workflow '{workflow_id}' "
        f"({node_count} nodes, {edge_count} edges)"
    )
    return config


# ---------------------------------------------------------------------------
# Combined loader
# ---------------------------------------------------------------------------


def load_all_configs(validate: bool = True) -> dict[str, dict[str, Any]]:
    """Load all configuration files.

    Args:
        validate: Whether to validate configurations.

    Returns:
        Dictionary with 'agents' and 'workflows' configs.

    Raises:
        ConfigError: If loading fails.
        ConfigValidationError: If validation fails.
    """
    agents_config = load_agents_config(validate=validate)
    workflows_config = load_workflows_config(
        agents_config=agents_config,
        validate=validate,
    )
    return {
        "agents": agents_config,
        "workflows": workflows_config,
    }


# ---------------------------------------------------------------------------
# Accessor helpers
# ---------------------------------------------------------------------------


def get_agent_config(
    agent_name: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get configuration for a specific agent.

    Returns the raw per-agent dict. Use get_effective_agent_config()
    if you need defaults merged in.

    Args:
        agent_name: Name of the agent.
        config: Agents config (loaded if not provided).

    Returns:
        Agent configuration dictionary.

    Raises:
        ConfigError: If agent not found.
    """
    if config is None:
        config = load_agents_config()

    agents = config.get("agents", {})
    if agent_name not in agents:
        raise ConfigError(f"Agent '{agent_name}' not found in configuration")

    return agents[agent_name]


def get_effective_agent_config(
    agent_name: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get resolved agent config with defaults merged in.

    Merge order (later overrides earlier):
      agents.yaml defaults → per-agent fields

    Args:
        agent_name: Name of the agent.
        config: Agents config (loaded if not provided).

    Returns:
        Merged agent configuration dictionary.

    Raises:
        ConfigError: If agent not found.
    """
    if config is None:
        config = load_agents_config()

    agent = get_agent_config(agent_name, config)
    defaults = config.get("defaults", {})

    # Start from defaults, overlay per-agent fields
    merged = {**defaults, **agent}

    # Merge nested retry block if both levels define it
    if "retry" in defaults and "retry" in agent:
        merged["retry"] = {**defaults["retry"], **agent["retry"]}

    return merged


def get_workflow_config(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get the workflow metadata block.

    In v1.2 there is a single workflow per file (no named map).

    Args:
        config: Workflows config (loaded if not provided).

    Returns:
        The workflow: block as a dictionary.

    Raises:
        ConfigError: If workflow block not found.
    """
    if config is None:
        config = load_workflows_config()

    workflow = config.get("workflow")
    if not workflow:
        raise ConfigError("'workflow' block not found in workflows config")

    return workflow


def get_edge_routes(
    from_node: str,
    config: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """Get the condition routes for a conditional edge.

    Scans the edges list for the first edge with the given from_node
    that has a condition block, and returns its routes dict.

    Args:
        from_node: Source node name (e.g. "critic_1").
        config: Workflows config (loaded if not provided).

    Returns:
        Routes dict mapping decision strings to node names,
        or None if no conditional edge exists for this node.

    Example:
        get_edge_routes("critic_1")
        → {"pass": "reconciler", "fail_retry": "extractor", "fail_max": "end"}
    """
    if config is None:
        config = load_workflows_config()

    for edge in config.get("edges", []):
        if edge.get("from") == from_node and "condition" in edge:
            return edge["condition"].get("routes")

    return None


def get_unconditional_target(
    from_node: str,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Get the target node for an unconditional edge.

    Args:
        from_node: Source node name (e.g. "extractor").
        config: Workflows config (loaded if not provided).

    Returns:
        Target node name, or None if no unconditional edge exists.
    """
    if config is None:
        config = load_workflows_config()

    for edge in config.get("edges", []):
        if edge.get("from") == from_node and "to" in edge:
            return edge["to"]

    return None


def resolve_agents_ref(workflows_config: dict[str, Any]) -> Path:
    """Resolve the agents_ref path from workflows.yaml.

    Reads the agents_ref field and resolves it relative to workflows.yaml
    so that the agents file location is fully config-driven.

    Args:
        workflows_config: Loaded workflows configuration.

    Returns:
        Absolute path to the agents.yaml file.

    Raises:
        ConfigError: If agents_ref is missing or the file does not exist.
    """
    agents_ref = workflows_config.get("agents_ref")
    if not agents_ref:
        raise ConfigError("'agents_ref' not found in workflows config")

    # Resolve relative to the workflows.yaml location
    agents_path = (_WORKFLOWS_FILE.parent / agents_ref).resolve()
    if not agents_path.exists():
        raise ConfigError(f"agents_ref path does not exist: {agents_path}")

    return agents_path


def build_agent_functions(
    agents_config: dict[str, Any],
    workflows_config: dict[str, Any],
) -> dict[str, Callable]:
    """Build all agent callables from YAML config.

    Iterates over workflow nodes, resolves each agent's effective config
    (defaults merged in), and calls the factory to build the callable.
    Returns a single dict keyed by node name — no separate agent/critic split.

    Args:
        agents_config: Loaded agents configuration.
        workflows_config: Loaded workflows configuration.

    Returns:
        Dict mapping node_name → agent callable, ready for build_workflow_graph().

    Raises:
        ConfigError: If any agent cannot be built.
    """
    from src.core.agent_factory import build_agent_fn

    agents_dir = resolve_agents_ref(workflows_config).parent
    nodes = workflows_config.get("nodes", {})
    functions: dict[str, Callable] = {}

    for node_name, node_def in nodes.items():
        node_type = node_def.get("type")
        if node_type == "end":
            continue

        agent_key = node_def.get("agent", node_name)
        effective_cfg = get_effective_agent_config(agent_key, agents_config)

        try:
            fn = build_agent_fn(agent_key, effective_cfg, agents_dir)
            functions[node_name] = fn
            logger.debug(
                f"Built agent function for node '{node_name}' "
                f"(agent='{agent_key}', execution='{effective_cfg.get('execution', 'llm')}')"
            )
        except Exception as e:
            raise ConfigError(f"Failed to build agent '{agent_key}': {e}") from e

    logger.info(f"Built {len(functions)} agent functions from YAML config")
    return functions


def resolve_callable(dotted_path: str) -> Callable:
    """Dynamically import and return a callable from a dotted path.

    Args:
        dotted_path: Fully-qualified Python callable
                     (e.g. "src.core.conditions.route_critic_1").

    Returns:
        The callable object.

    Raises:
        ConfigError: If the module or attribute cannot be imported.
    """
    parts = dotted_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ConfigError(
            f"Invalid callable path '{dotted_path}': expected 'module.callable'"
        )
    module_path, attr_name = parts
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise ConfigError(f"Cannot import module '{module_path}': {e}")
    try:
        return getattr(module, attr_name)
    except AttributeError:
        raise ConfigError(
            f"Module '{module_path}' has no attribute '{attr_name}'"
        )
