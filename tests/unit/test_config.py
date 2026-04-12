"""Unit tests for configuration loading and validation (AGENTFLOW v1.2)."""

from pathlib import Path

import pytest
import yaml

from src.config.loader import (
    ConfigError,
    ConfigValidationError,
    get_agent_config,
    get_edge_routes,
    get_effective_agent_config,
    get_unconditional_target,
    get_workflow_config,
    load_agents_config,
    load_all_configs,
    load_workflows_config,
    load_yaml,
    resolve_callable,
    validate_agents_config,
    validate_workflows_config,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal valid v1.2 configs for use in validation tests
# ---------------------------------------------------------------------------

def _minimal_agents_config() -> dict:
    """Minimal valid agents config with all 7 required KYC agents."""
    agent = {
        "role": "Test Role",
        "goal": "Test goal",
        "backstory": "Test backstory.",
        "input_keys": ["documents"],
        "output_key": "extracted_persons",
        "system_prompt": {"file": "../prompts/extractor.md"},
        "output_schema": {"ref": "src.models.person.ExtractedPerson"},
    }
    return {
        "version": "1.2",
        "agents": {
            "extractor": {**agent},
            "critic_1": {**agent, "output_key": "last_critic_feedback"},
            "reconciler": {**agent, "output_key": "reconciled_persons"},
            "critic_2": {**agent, "output_key": "last_critic_feedback"},
            "classifier": {**agent, "output_key": "classified_persons"},
            "critic_3": {**agent, "output_key": "last_critic_feedback"},
            "formatter": {**agent, "output_key": "document_manifest"},
        },
    }


def _minimal_workflows_config() -> dict:
    """Minimal valid workflows config with nodes + edges."""
    return {
        "version": "1.2",
        "workflow": {
            "id": "kyc_document_processing",
            "name": "KYC Test",
            "entry_point": "__start__",
        },
        "nodes": {
            "extractor": {"type": "agent", "agent": "extractor"},
            "critic_1": {"type": "agent", "agent": "critic_1"},
            "end": {"type": "end"},
        },
        "edges": [
            {"from": "__start__", "to": "extractor"},
            {"from": "extractor", "to": "critic_1"},
            {
                "from": "critic_1",
                "condition": {
                    "fn": "src.core.conditions.route_critic_1",
                    "routes": {
                        "pass": "end",
                        "fail_retry": "extractor",
                        "fail_max": "end",
                    },
                },
            },
            {"from": "critic_1", "to": "end"},
        ],
    }


# ---------------------------------------------------------------------------
# TestLoadYaml
# ---------------------------------------------------------------------------


class TestLoadYaml:
    def test_load_valid_yaml(self, tmp_path):
        f = tmp_path / "test.yaml"
        f.write_text("key: value\nlist:\n  - item1\n  - item2")
        result = load_yaml(f)
        assert result["key"] == "value"
        assert result["list"] == ["item1", "item2"]

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_yaml(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml(self, tmp_path):
        f = tmp_path / "invalid.yaml"
        f.write_text("key: [invalid yaml")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_yaml(f)


# ---------------------------------------------------------------------------
# TestLoadAgentsConfig — bundled agents.yaml
# ---------------------------------------------------------------------------


class TestLoadAgentsConfig:
    def test_load_bundled_agents_config(self):
        config = load_agents_config()
        assert config is not None
        assert "version" in config
        assert "agents" in config

    def test_bundled_config_version(self):
        config = load_agents_config()
        assert config["version"] == "1.2"

    def test_bundled_config_has_all_agents(self):
        config = load_agents_config()
        agents = config["agents"]
        required = [
            "extractor", "critic_1", "reconciler",
            "critic_2", "classifier", "critic_3", "formatter",
        ]
        for name in required:
            assert name in agents, f"Missing agent: {name}"

    def test_agent_has_v12_required_fields(self):
        config = load_agents_config()
        for name, agent in config["agents"].items():
            assert "role" in agent,        f"Agent {name} missing 'role'"
            assert "goal" in agent,        f"Agent {name} missing 'goal'"
            assert "backstory" in agent,   f"Agent {name} missing 'backstory'"
            assert "input_keys" in agent,  f"Agent {name} missing 'input_keys'"
            assert "output_key" in agent,  f"Agent {name} missing 'output_key'"
            # system_prompt is only required for LLM agents (not rule-based)
            execution = agent.get("execution", "llm")
            if execution == "llm":
                assert "system_prompt" in agent, f"Agent {name} missing 'system_prompt'"
            elif execution == "rule":
                assert "rule_fn" in agent, f"Agent {name} missing 'rule_fn'"

    def test_agent_system_prompt_has_file_or_inline(self):
        config = load_agents_config()
        for name, agent in config["agents"].items():
            # system_prompt only exists on LLM agents
            if agent.get("execution", "llm") != "llm":
                continue
            sp = agent["system_prompt"]
            assert "file" in sp or "inline" in sp, (
                f"Agent {name}: system_prompt must have 'file' or 'inline'"
            )

    def test_agent_output_schema_has_ref_or_example(self):
        config = load_agents_config()
        for name, agent in config["agents"].items():
            os_ = agent.get("output_schema")
            if os_ is not None:
                assert "ref" in os_ or "example" in os_, (
                    f"Agent {name}: output_schema must have 'ref' or 'example'"
                )

    def test_no_old_v10_fields_present(self):
        """v1.0 fields must be absent from agents."""
        config = load_agents_config()
        for name, agent in config["agents"].items():
            assert "type" not in agent,           f"Agent {name} has old 'type' field"
            assert "prompt_file" not in agent,    f"Agent {name} has old 'prompt_file' field"
            assert "validates_phase" not in agent, f"Agent {name} has old 'validates_phase'"
            assert "validation_rules" not in agent, f"Agent {name} has old 'validation_rules'"
            assert "llm" not in agent,            f"Agent {name} has old nested 'llm' block"


# ---------------------------------------------------------------------------
# TestValidateAgentsConfig
# ---------------------------------------------------------------------------


class TestValidateAgentsConfig:
    def test_valid_config_passes(self):
        validate_agents_config(_minimal_agents_config())  # should not raise

    def test_missing_rule_fn_fails(self):
        """Rule-based agent without rule_fn raises ConfigValidationError."""
        config = _minimal_agents_config()
        config["agents"]["critic_2"] = {
            "role": "R", "goal": "G", "backstory": "B",
            "input_keys": [], "output_key": "last_critic_feedback",
            "execution": "rule",
            # rule_fn intentionally omitted
        }
        with pytest.raises(ConfigValidationError) as exc:
            validate_agents_config(config)
        assert any("rule_fn" in str(e) for e in exc.value.errors)

    def test_missing_system_prompt_fails(self):
        config = _minimal_agents_config()
        del config["agents"]["extractor"]["system_prompt"]
        with pytest.raises(ConfigValidationError) as exc:
            validate_agents_config(config)
        assert any("system_prompt" in str(e) for e in exc.value.errors)

    def test_invalid_output_schema_fails(self):
        config = _minimal_agents_config()
        config["agents"]["extractor"]["output_schema"] = {"invalid_key": "something"}
        with pytest.raises(ConfigValidationError) as exc:
            validate_agents_config(config)
        assert any("output_schema" in str(e) for e in exc.value.errors)


# ---------------------------------------------------------------------------
# TestLoadWorkflowsConfig — bundled workflows.yaml
# ---------------------------------------------------------------------------


class TestLoadWorkflowsConfig:
    def test_load_bundled_workflows_config(self):
        config = load_workflows_config()
        assert config is not None
        assert "version" in config

    def test_bundled_config_version(self):
        config = load_workflows_config()
        assert config["version"] == "1.2"

    def test_bundled_config_has_workflow_block(self):
        config = load_workflows_config()
        assert "workflow" in config
        assert config["workflow"]["id"] == "kyc_document_processing"

    def test_bundled_config_has_nodes(self):
        config = load_workflows_config()
        assert "nodes" in config
        expected_nodes = [
            "extractor", "critic_1", "reconciler",
            "critic_2", "classifier", "critic_3", "formatter", "end",
        ]
        for node in expected_nodes:
            assert node in config["nodes"], f"Missing node: {node}"

    def test_bundled_config_has_edges(self):
        config = load_workflows_config()
        assert "edges" in config
        assert len(config["edges"]) > 0

    def test_no_old_v10_fields_present(self):
        config = load_workflows_config()
        assert "workflows" not in config,   "Old 'workflows' map present"
        assert "transitions" not in config, "Old 'transitions' block present"
        assert "events" not in config,      "Old 'events' block present"


# ---------------------------------------------------------------------------
# TestValidateWorkflowsConfig
# ---------------------------------------------------------------------------


class TestValidateWorkflowsConfig:
    def test_valid_config_passes(self):
        wf = _minimal_workflows_config()
        ag = _minimal_agents_config()
        validate_workflows_config(wf, ag)  # should not raise

    def test_unknown_agent_in_node_fails(self):
        wf = _minimal_workflows_config()
        wf["nodes"]["bad_node"] = {"type": "agent", "agent": "nonexistent"}
        ag = _minimal_agents_config()
        with pytest.raises(ConfigValidationError) as exc:
            validate_workflows_config(wf, ag)
        assert any("nonexistent" in str(e) for e in exc.value.errors)

    def test_unknown_edge_target_fails(self):
        wf = _minimal_workflows_config()
        wf["edges"].append({"from": "extractor", "to": "ghost_node"})
        ag = _minimal_agents_config()
        with pytest.raises(ConfigValidationError) as exc:
            validate_workflows_config(wf, ag)
        assert any("ghost_node" in str(e) for e in exc.value.errors)

    def test_unknown_condition_route_target_fails(self):
        wf = _minimal_workflows_config()
        wf["edges"].append({
            "from": "extractor",
            "condition": {
                "fn": "src.core.conditions.route_critic_1",
                "routes": {"pass": "ghost_node"},
            },
        })
        ag = _minimal_agents_config()
        with pytest.raises(ConfigValidationError) as exc:
            validate_workflows_config(wf, ag)
        assert any("ghost_node" in str(e) for e in exc.value.errors)


# ---------------------------------------------------------------------------
# TestLoadAllConfigs
# ---------------------------------------------------------------------------


class TestLoadAllConfigs:
    def test_load_all_configs(self):
        configs = load_all_configs()
        assert "agents" in configs
        assert "workflows" in configs
        assert configs["agents"]["agents"] is not None
        assert configs["workflows"]["nodes"] is not None


# ---------------------------------------------------------------------------
# TestGetAgentConfig
# ---------------------------------------------------------------------------


class TestGetAgentConfig:
    def test_get_existing_agent(self):
        config = get_agent_config("extractor")
        assert "role" in config
        assert "goal" in config
        assert "input_keys" in config

    def test_get_nonexistent_agent_raises(self):
        with pytest.raises(ConfigError, match="not found"):
            get_agent_config("nonexistent_agent")


# ---------------------------------------------------------------------------
# TestGetEffectiveAgentConfig
# ---------------------------------------------------------------------------


class TestGetEffectiveAgentConfig:
    def test_defaults_merged_into_agent(self):
        agents_config = {
            "version": "1.2",
            "defaults": {"model": "openai/gpt-4o-mini", "temperature": 0},
            "agents": {
                "extractor": {
                    "role": "R", "goal": "G", "backstory": "B",
                    "input_keys": ["documents"], "output_key": "extracted_persons",
                    "system_prompt": {"inline": "test prompt"},
                },
            },
        }
        result = get_effective_agent_config("extractor", agents_config)
        assert result["model"] == "openai/gpt-4o-mini"
        assert result["temperature"] == 0
        assert result["role"] == "R"

    def test_agent_overrides_default(self):
        agents_config = {
            "version": "1.2",
            "defaults": {"model": "openai/gpt-4o-mini", "temperature": 0},
            "agents": {
                "extractor": {
                    "role": "R", "goal": "G", "backstory": "B",
                    "model": "openai/gpt-4o",  # override
                    "input_keys": ["documents"], "output_key": "extracted_persons",
                    "system_prompt": {"inline": "test prompt"},
                },
            },
        }
        result = get_effective_agent_config("extractor", agents_config)
        assert result["model"] == "openai/gpt-4o"

    def test_retry_blocks_merged(self):
        agents_config = {
            "version": "1.2",
            "defaults": {"retry": {"max_attempts": 4, "backoff": "exponential"}},
            "agents": {
                "extractor": {
                    "role": "R", "goal": "G", "backstory": "B",
                    "input_keys": ["documents"], "output_key": "out",
                    "system_prompt": {"inline": "p"},
                    "retry": {"delay_seconds": 2},  # partial override
                },
            },
        }
        result = get_effective_agent_config("extractor", agents_config)
        assert result["retry"]["max_attempts"] == 4
        assert result["retry"]["delay_seconds"] == 2


# ---------------------------------------------------------------------------
# TestGetWorkflowConfig
# ---------------------------------------------------------------------------


class TestGetWorkflowConfig:
    def test_get_workflow_config(self):
        config = get_workflow_config()
        assert config is not None
        assert config["id"] == "kyc_document_processing"
        assert config["entry_point"] == "__start__"

    def test_missing_workflow_block_raises(self):
        with pytest.raises(ConfigError, match="workflow"):
            get_workflow_config(config={})


# ---------------------------------------------------------------------------
# TestGetEdgeRoutes
# ---------------------------------------------------------------------------


class TestGetEdgeRoutes:
    def test_get_critic_1_routes(self):
        # critic_1 now goes unconditionally to extractor_critic_router;
        # the router node itself (type: router) handles conditional logic via Command.
        routes = get_edge_routes("critic_1")
        assert routes is None  # no conditional edge from critic_1

    def test_get_critic_2_routes(self):
        routes = get_edge_routes("critic_2")
        assert routes["pass"] == "classifier"
        assert routes["fail_retry"] == "reconciler"

    def test_get_critic_3_routes(self):
        routes = get_edge_routes("critic_3")
        assert routes["pass"] == "formatter"
        assert routes["fail_retry"] == "classifier"

    def test_no_conditional_edge_returns_none(self):
        result = get_edge_routes("extractor")
        assert result is None

    def test_unknown_node_returns_none(self):
        result = get_edge_routes("nonexistent_node")
        assert result is None


# ---------------------------------------------------------------------------
# TestGetUnconditionalTarget
# ---------------------------------------------------------------------------


class TestGetUnconditionalTarget:
    def test_extractor_goes_to_critic_1(self):
        assert get_unconditional_target("extractor") == "critic_1"

    def test_reconciler_goes_to_critic_2(self):
        assert get_unconditional_target("reconciler") == "critic_2"

    def test_classifier_goes_to_critic_3(self):
        assert get_unconditional_target("classifier") == "critic_3"

    def test_formatter_goes_to_end(self):
        assert get_unconditional_target("formatter") == "end"

    def test_unknown_node_returns_none(self):
        assert get_unconditional_target("nonexistent") is None


# ---------------------------------------------------------------------------
# TestResolveCallable
# ---------------------------------------------------------------------------


class TestResolveCallable:
    def test_resolve_valid_callable(self):
        fn = resolve_callable("src.core.conditions.route_on_critic_decision")
        assert callable(fn)

    def test_resolve_all_critic_routes(self):
        # Single generic routing function replaces per-critic functions
        fn = resolve_callable("src.core.conditions.route_on_critic_decision")
        assert callable(fn)

    def test_resolve_invalid_module_raises(self):
        with pytest.raises(ConfigError, match="Cannot import"):
            resolve_callable("nonexistent.module.fn")

    def test_resolve_invalid_attribute_raises(self):
        with pytest.raises(ConfigError, match="no attribute"):
            resolve_callable("src.core.conditions.nonexistent_fn")

    def test_resolve_bad_path_format_raises(self):
        with pytest.raises(ConfigError, match="Invalid callable"):
            resolve_callable("no_dots_here")


# ---------------------------------------------------------------------------
# TestConfigIntegration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    def test_full_workflow_path_via_edges(self):
        """Trace the happy path through edges using get_edge_routes / get_unconditional_target."""
        path = []
        current = "extractor"

        while current not in ("end", None):
            path.append(current)
            if current.startswith("critic_"):
                routes = get_edge_routes(current)
                current = routes["pass"] if routes else None
            else:
                current = get_unconditional_target(current)

        path.append(current)

        assert path == [
            "extractor", "critic_1",
            "reconciler", "critic_2",
            "classifier", "critic_3",
            "formatter", "end",
        ]

    def test_retry_loop_via_edges(self):
        """Trace extraction retry path via edge routes."""
        current = get_unconditional_target("extractor")   # → critic_1
        assert current == "critic_1"

        routes = get_edge_routes("critic_1")
        current = routes["fail_retry"]                    # → extractor
        assert current == "extractor"

        current = get_unconditional_target(current)       # → critic_1
        assert current == "critic_1"

    def test_fail_max_path(self):
        """fail_max routes to end."""
        routes = get_edge_routes("critic_1")
        assert routes["fail_max"] == "end"
