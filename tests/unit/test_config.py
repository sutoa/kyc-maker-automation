"""Unit tests for configuration loading and validation."""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.config.loader import (
    ConfigError,
    ConfigValidationError,
    get_agent_config,
    get_transition,
    get_workflow_config,
    load_agents_config,
    load_all_configs,
    load_workflows_config,
    load_yaml,
    validate_agents_config,
    validate_workflows_config,
)


class TestLoadYaml:
    """Tests for YAML loading."""

    def test_load_valid_yaml(self, tmp_path):
        """Test loading a valid YAML file."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nlist:\n  - item1\n  - item2")

        result = load_yaml(yaml_file)

        assert result["key"] == "value"
        assert result["list"] == ["item1", "item2"]

    def test_load_missing_file(self, tmp_path):
        """Test loading a non-existent file raises error."""
        with pytest.raises(ConfigError, match="not found"):
            load_yaml(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML raises error."""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("key: [invalid yaml")

        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_yaml(yaml_file)


class TestLoadAgentsConfig:
    """Tests for agents configuration loading."""

    def test_load_bundled_agents_config(self):
        """Test loading the bundled agents.yaml."""
        config = load_agents_config()

        assert config is not None
        assert "version" in config
        assert "agents" in config

    def test_bundled_config_has_all_agents(self):
        """Test that bundled config has all required agents."""
        config = load_agents_config()
        agents = config["agents"]

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
            assert agent_name in agents, f"Missing agent: {agent_name}"

    def test_agent_has_required_fields(self):
        """Test that agents have required fields."""
        config = load_agents_config()

        for name, agent in config["agents"].items():
            assert "name" in agent, f"Agent {name} missing 'name'"
            assert "type" in agent, f"Agent {name} missing 'type'"
            assert "prompt_file" in agent, f"Agent {name} missing 'prompt_file'"

    def test_critic_agents_have_validates_phase(self):
        """Test that critic agents have validates_phase."""
        config = load_agents_config()

        for name, agent in config["agents"].items():
            if agent.get("type") == "critic":
                assert "validates_phase" in agent, f"Critic {name} missing 'validates_phase'"

    def test_load_without_validation(self, tmp_path):
        """Test loading config without validation."""
        yaml_file = tmp_path / "agents.yaml"
        yaml_file.write_text("version: '1.0'\nagents: {}")

        # Should not raise even with missing agents
        config = load_yaml(yaml_file)
        assert config["version"] == "1.0"


class TestValidateAgentsConfig:
    """Tests for agents configuration validation."""

    def test_valid_config_passes(self):
        """Test that valid config passes validation."""
        config = {
            "version": "1.0",
            "agents": {
                "extractor": {"name": "extractor", "type": "extractor", "prompt_file": "extractor.md"},
                "critic_1": {
                    "name": "critic_1",
                    "type": "critic",
                    "prompt_file": "critic_1.md",
                    "validates_phase": "extraction",
                },
                "reconciler": {"name": "reconciler", "type": "reconciler", "prompt_file": "reconciler.md"},
                "critic_2": {
                    "name": "critic_2",
                    "type": "critic",
                    "prompt_file": "critic_2.md",
                    "validates_phase": "reconciliation",
                },
                "classifier": {"name": "classifier", "type": "classifier", "prompt_file": "classifier.md"},
                "critic_3": {
                    "name": "critic_3",
                    "type": "critic",
                    "prompt_file": "critic_3.md",
                    "validates_phase": "classification",
                },
                "formatter": {"name": "formatter", "type": "formatter", "prompt_file": "formatter.md"},
            },
        }

        # Should not raise
        validate_agents_config(config)

    def test_missing_required_agent_fails(self):
        """Test that missing required agent fails validation."""
        config = {
            "version": "1.0",
            "agents": {
                "extractor": {"name": "extractor", "type": "extractor", "prompt_file": "extractor.md"},
                # Missing other required agents
            },
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_agents_config(config)

        assert "critic_1" in str(exc_info.value.errors)

    def test_invalid_critic_phase_fails(self):
        """Test that invalid critic phase fails validation."""
        config = {
            "version": "1.0",
            "agents": {
                "extractor": {"name": "extractor", "type": "extractor", "prompt_file": "extractor.md"},
                "critic_1": {
                    "name": "critic_1",
                    "type": "critic",
                    "prompt_file": "critic_1.md",
                    "validates_phase": "invalid_phase",  # Invalid
                },
                "reconciler": {"name": "reconciler", "type": "reconciler", "prompt_file": "reconciler.md"},
                "critic_2": {
                    "name": "critic_2",
                    "type": "critic",
                    "prompt_file": "critic_2.md",
                    "validates_phase": "reconciliation",
                },
                "classifier": {"name": "classifier", "type": "classifier", "prompt_file": "classifier.md"},
                "critic_3": {
                    "name": "critic_3",
                    "type": "critic",
                    "prompt_file": "critic_3.md",
                    "validates_phase": "classification",
                },
                "formatter": {"name": "formatter", "type": "formatter", "prompt_file": "formatter.md"},
            },
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_agents_config(config)

        assert "invalid_phase" in str(exc_info.value.errors)


class TestLoadWorkflowsConfig:
    """Tests for workflows configuration loading."""

    def test_load_bundled_workflows_config(self):
        """Test loading the bundled workflows.yaml."""
        config = load_workflows_config()

        assert config is not None
        assert "version" in config
        assert "workflows" in config

    def test_bundled_config_has_kyc_workflow(self):
        """Test that bundled config has the KYC workflow."""
        config = load_workflows_config()

        assert "kyc_document_processing" in config["workflows"]

    def test_workflow_has_required_fields(self):
        """Test that workflow has required fields."""
        config = load_workflows_config()
        workflow = config["workflows"]["kyc_document_processing"]

        assert "initial_state" in workflow
        assert "terminal_states" in workflow
        assert "transitions" in workflow

    def test_workflow_transitions_exist(self):
        """Test that all expected transitions exist."""
        config = load_workflows_config()
        transitions = config["workflows"]["kyc_document_processing"]["transitions"]

        expected_agents = [
            "extractor",
            "critic_1",
            "reconciler",
            "critic_2",
            "classifier",
            "critic_3",
            "formatter",
        ]

        for agent in expected_agents:
            assert agent in transitions, f"Missing transition for {agent}"


class TestValidateWorkflowsConfig:
    """Tests for workflows configuration validation."""

    def test_valid_config_passes(self):
        """Test that valid config passes validation."""
        agents_config = {
            "agents": {
                "extractor": {},
                "critic_1": {},
            }
        }
        workflows_config = {
            "workflows": {
                "test_workflow": {
                    "initial_state": "extractor",
                    "terminal_states": ["COMPLETED", "FAILED"],
                    "transitions": {
                        "extractor": {"on_complete": "critic_1"},
                        "critic_1": {"on_pass": "COMPLETED", "on_fail_max": "FAILED"},
                    },
                }
            }
        }

        # Should not raise
        validate_workflows_config(workflows_config, agents_config)

    def test_unknown_agent_in_transitions_fails(self):
        """Test that unknown agent in transitions fails."""
        agents_config = {"agents": {"extractor": {}}}
        workflows_config = {
            "workflows": {
                "test_workflow": {
                    "initial_state": "extractor",
                    "terminal_states": ["COMPLETED"],
                    "transitions": {
                        "unknown_agent": {"on_complete": "COMPLETED"},
                    },
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_workflows_config(workflows_config, agents_config)

        assert "unknown_agent" in str(exc_info.value.errors)

    def test_unknown_transition_target_fails(self):
        """Test that unknown transition target fails."""
        agents_config = {"agents": {"extractor": {}}}
        workflows_config = {
            "workflows": {
                "test_workflow": {
                    "initial_state": "extractor",
                    "terminal_states": ["COMPLETED"],
                    "transitions": {
                        "extractor": {"on_complete": "unknown_target"},
                    },
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_workflows_config(workflows_config, agents_config)

        assert "unknown_target" in str(exc_info.value.errors)

    def test_unknown_initial_state_fails(self):
        """Test that unknown initial state fails."""
        agents_config = {"agents": {"extractor": {}}}
        workflows_config = {
            "workflows": {
                "test_workflow": {
                    "initial_state": "unknown_agent",
                    "terminal_states": ["COMPLETED"],
                    "transitions": {},
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_workflows_config(workflows_config, agents_config)

        assert "unknown_agent" in str(exc_info.value.errors)


class TestLoadAllConfigs:
    """Tests for loading all configurations."""

    def test_load_all_configs(self):
        """Test loading all configs at once."""
        configs = load_all_configs()

        assert "agents" in configs
        assert "workflows" in configs
        assert configs["agents"]["agents"] is not None
        assert configs["workflows"]["workflows"] is not None


class TestGetAgentConfig:
    """Tests for getting individual agent configurations."""

    def test_get_existing_agent(self):
        """Test getting an existing agent's config."""
        config = get_agent_config("extractor")

        assert config["name"] == "extractor"
        assert config["type"] == "extractor"

    def test_get_nonexistent_agent_raises(self):
        """Test that getting non-existent agent raises error."""
        with pytest.raises(ConfigError, match="not found"):
            get_agent_config("nonexistent_agent")

    def test_get_critic_agent(self):
        """Test getting a critic agent's config."""
        config = get_agent_config("critic_1")

        assert config["type"] == "critic"
        assert config["validates_phase"] == "extraction"


class TestGetWorkflowConfig:
    """Tests for getting workflow configurations."""

    def test_get_default_workflow(self):
        """Test getting the default workflow config."""
        config = get_workflow_config()

        assert config is not None
        assert "transitions" in config

    def test_get_named_workflow(self):
        """Test getting a named workflow config."""
        config = get_workflow_config("kyc_document_processing")

        assert config is not None
        assert config["initial_state"] == "extractor"

    def test_get_nonexistent_workflow_raises(self):
        """Test that getting non-existent workflow raises error."""
        with pytest.raises(ConfigError, match="not found"):
            get_workflow_config("nonexistent_workflow")


class TestGetTransition:
    """Tests for getting workflow transitions."""

    def test_get_extractor_transition(self):
        """Test getting transition from extractor."""
        next_agent = get_transition("extractor")

        assert next_agent == "critic_1"

    def test_get_critic_pass_transition(self):
        """Test getting critic pass transition."""
        next_agent = get_transition("critic_1", decision="pass")

        assert next_agent == "reconciler"

    def test_get_critic_fail_retry_transition(self):
        """Test getting critic fail_retry transition."""
        next_agent = get_transition("critic_1", decision="fail_retry")

        assert next_agent == "extractor"

    def test_get_critic_fail_max_transition(self):
        """Test getting critic fail_max transition."""
        next_agent = get_transition("critic_1", decision="fail_max")

        assert next_agent == "FAILED"

    def test_get_formatter_transition(self):
        """Test getting formatter transition."""
        next_agent = get_transition("formatter")

        assert next_agent == "COMPLETED"

    def test_get_invalid_agent_returns_none(self):
        """Test that invalid agent returns None."""
        next_agent = get_transition("nonexistent")

        assert next_agent is None


class TestConfigIntegration:
    """Integration tests for configuration loading."""

    def test_full_workflow_path_extraction_to_completion(self):
        """Test that a complete workflow path can be traced."""
        # Simulate successful workflow path
        path = []
        current = "extractor"

        while current not in ("COMPLETED", "FAILED", None):
            path.append(current)
            if current.startswith("critic"):
                current = get_transition(current, decision="pass")
            else:
                current = get_transition(current)

        path.append(current)

        expected_path = [
            "extractor",
            "critic_1",
            "reconciler",
            "critic_2",
            "classifier",
            "critic_3",
            "formatter",
            "COMPLETED",
        ]

        assert path == expected_path

    def test_retry_loop_path(self):
        """Test that retry loops work correctly."""
        # Simulate extraction failing and retrying
        current = "extractor"
        current = get_transition(current)  # -> critic_1
        assert current == "critic_1"

        current = get_transition(current, decision="fail_retry")  # -> extractor
        assert current == "extractor"

        current = get_transition(current)  # -> critic_1
        assert current == "critic_1"

    def test_max_retry_failure_path(self):
        """Test that max retry leads to failure."""
        current = "critic_1"
        current = get_transition(current, decision="fail_max")

        assert current == "FAILED"
