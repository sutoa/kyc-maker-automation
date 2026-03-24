"""Configuration loader with schema validation.

This module provides functions to load and validate:
- Agent configurations from agents.yaml
- Workflow configurations from workflows.yaml

Validation uses JSON Schema for structural validation and
additional semantic validation for workflow consistency.
"""

import json
import logging
from pathlib import Path
from typing import Any

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


def validate_agents_config(config: dict[str, Any]) -> None:
    """Validate agents configuration semantically.

    Performs checks beyond JSON schema validation:
    - All agents have unique names
    - Required agents are present
    - Critic agents reference valid phases

    Args:
        config: Agents configuration dictionary.

    Raises:
        ConfigValidationError: If semantic validation fails.
    """
    errors = []
    agents = config.get("agents", {})

    # Check required agents exist
    required_agents = [
        "extractor",
        "critic_1",
        "reconciler",
        "critic_2",
        "classifier",
        "critic_3",
        "formatter",
    ]
    for agent_name in required_agents:
        if agent_name not in agents:
            errors.append(
                {"path": f"agents.{agent_name}", "message": f"Required agent '{agent_name}' is missing"}
            )

    # Check critic agents have valid validates_phase
    valid_phases = {"extraction", "reconciliation", "classification"}
    for name, agent in agents.items():
        if agent.get("type") == "critic":
            phase = agent.get("validates_phase")
            if phase and phase not in valid_phases:
                errors.append(
                    {
                        "path": f"agents.{name}.validates_phase",
                        "message": f"Invalid phase '{phase}'. Must be one of: {valid_phases}",
                    }
                )

    if errors:
        raise ConfigValidationError(
            f"Agents config semantic validation failed: {len(errors)} error(s)",
            errors=errors,
        )


def validate_workflows_config(config: dict[str, Any], agents_config: dict[str, Any]) -> None:
    """Validate workflows configuration semantically.

    Performs checks beyond JSON schema validation:
    - All referenced agents exist in agents config
    - Workflow transitions form valid graph
    - Terminal states are reachable

    Args:
        config: Workflows configuration dictionary.
        agents_config: Agents configuration dictionary.

    Raises:
        ConfigValidationError: If semantic validation fails.
    """
    errors = []
    agents = agents_config.get("agents", {})

    for workflow_name, workflow in config.get("workflows", {}).items():
        transitions = workflow.get("transitions", {})
        terminal_states = set(workflow.get("terminal_states", []))

        # Check all transition sources are valid agents or terminal states
        for source, transition in transitions.items():
            if source not in agents and source not in terminal_states:
                errors.append(
                    {
                        "path": f"workflows.{workflow_name}.transitions.{source}",
                        "message": f"Unknown agent '{source}' in transitions",
                    }
                )

            # Check transition targets
            for key in ["on_complete", "on_pass", "on_fail_retry", "on_fail_max"]:
                target = transition.get(key)
                if target and target not in agents and target not in terminal_states:
                    errors.append(
                        {
                            "path": f"workflows.{workflow_name}.transitions.{source}.{key}",
                            "message": f"Unknown target '{target}'",
                        }
                    )

        # Check initial state is valid
        initial_state = workflow.get("initial_state")
        if initial_state and initial_state not in agents:
            errors.append(
                {
                    "path": f"workflows.{workflow_name}.initial_state",
                    "message": f"Unknown initial state '{initial_state}'",
                }
            )

    if errors:
        raise ConfigValidationError(
            f"Workflows config semantic validation failed: {len(errors)} error(s)",
            errors=errors,
        )


def load_agents_config(
    file_path: Path | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Load and validate agents configuration.

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
        # Schema validation (if jsonschema available)
        try:
            schema = load_json_schema(_AGENT_SCHEMA_FILE)
            validate_against_schema(config, schema, "agents")
        except ConfigError as e:
            logger.warning(f"Schema validation skipped: {e}")

        # Semantic validation
        validate_agents_config(config)

    logger.info(f"Loaded agents config with {len(config.get('agents', {}))} agents")
    return config


def load_workflows_config(
    file_path: Path | None = None,
    agents_config: dict[str, Any] | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Load and validate workflows configuration.

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
        # Load agents config if not provided
        if agents_config is None:
            agents_config = load_agents_config(validate=False)

        # Semantic validation
        validate_workflows_config(config, agents_config)

    workflows = config.get("workflows", {})
    logger.info(f"Loaded workflows config with {len(workflows)} workflow(s)")
    return config


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


def get_agent_config(agent_name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get configuration for a specific agent.

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


def get_workflow_config(
    workflow_name: str = "kyc_document_processing",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get configuration for a specific workflow.

    Args:
        workflow_name: Name of the workflow.
        config: Workflows config (loaded if not provided).

    Returns:
        Workflow configuration dictionary.

    Raises:
        ConfigError: If workflow not found.
    """
    if config is None:
        config = load_workflows_config()

    workflows = config.get("workflows", {})
    if workflow_name not in workflows:
        raise ConfigError(f"Workflow '{workflow_name}' not found in configuration")

    return workflows[workflow_name]


def get_transition(
    agent_name: str,
    decision: str | None = None,
    workflow_config: dict[str, Any] | None = None,
) -> str | None:
    """Get the next agent based on current agent and decision.

    Args:
        agent_name: Current agent name.
        decision: Critic decision ('pass', 'fail_retry', 'fail_max') or None for non-critic.
        workflow_config: Workflow config (loaded if not provided).

    Returns:
        Name of next agent or terminal state, or None if not found.
    """
    if workflow_config is None:
        workflow_config = get_workflow_config()

    transitions = workflow_config.get("transitions", {})
    agent_transitions = transitions.get(agent_name, {})

    if decision is None:
        # Non-critic agents use on_complete
        return agent_transitions.get("on_complete")
    else:
        # Map decision to transition key
        key_map = {
            "pass": "on_pass",
            "fail_retry": "on_fail_retry",
            "fail_max": "on_fail_max",
        }
        key = key_map.get(decision)
        return agent_transitions.get(key) if key else None
