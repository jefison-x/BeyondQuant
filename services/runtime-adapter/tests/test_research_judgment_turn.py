"""ADR-0085 P4 real Runtime Adapter turn_runner (no carrier, no provider).

The pure prompt/parse/env logic is exercised here; the real carrier path is
proven separately by scripts/v091/continuation_p4/carrier_turn_runner_probe.py.
"""
from __future__ import annotations

import json

import pytest

from app import research_judgment_turn as turn


def test_prompt_embeds_the_bounded_stage_input_and_forbids_identity():
    admission = {"call_identity": "turn-a", "stage_input": {
        "schema_version": "research-stage-input.v1", "task_id": "task_" + "a" * 32,
        "stage": "backtest_analysis"}}
    prompt = turn.build_persona_prompt(admission, turn.RESEARCH_JUDGMENT_PERSONA_TOOL)
    assert "research-stage-input.v1" in prompt
    assert turn.RESEARCH_JUDGMENT_PERSONA_TOOL in prompt
    assert "Never invent or choose an object id" in prompt
    with pytest.raises(turn.ResearchJudgmentError):
        turn.build_persona_prompt({"stage_input": {}}, "byq_some_other_tool")
    with pytest.raises(turn.ResearchJudgmentError):
        turn.build_persona_prompt({"call_identity": "x"}, turn.RESEARCH_JUDGMENT_PERSONA_TOOL)


def test_extracts_the_closed_result_from_the_child_text():
    text = json.dumps({"proposal": {"proposal_kind": "backtest_analysis"},
                       "durable_evidence": {"kind": "none"}})
    result = turn.extract_closed_result(text, turn.RESEARCH_JUDGMENT_PERSONA_TOOL)
    # Only the proposal is returned; a "none" durable evidence adds no identity.
    assert result == {"proposal": {"proposal_kind": "backtest_analysis"}}
    fenced = "```json\n" + text + "\n```"
    assert turn.extract_closed_result(fenced, turn.RESEARCH_JUDGMENT_PERSONA_TOOL)["proposal"]


def test_bounded_turn_may_not_supply_a_durable_evidence_identity():
    # The model has no write tool; naming a durable BYQ object must fail closed,
    # which also keeps the stage's second (continue) call unreachable here.
    for evidence in ({"kind": "artifact", "id": "artifact_" + "a" * 32},
                     {"kind": "backtest_job", "id": "backtest_" + "a" * 32},
                     {"kind": "experiment", "id": "experiment_" + "a" * 32}):
        text = json.dumps({"proposal": {"proposal_kind": "backtest_analysis"},
                           "durable_evidence": evidence})
        with pytest.raises(turn.ResearchJudgmentError):
            turn.extract_closed_result(text, turn.RESEARCH_JUDGMENT_PERSONA_TOOL)


def test_malformed_or_widened_results_fail_closed():
    for bad in (None, "", "not json", json.dumps({"next_action": "execute"}),
                json.dumps({"proposal": "not-an-object"}),
                json.dumps({"proposal": {}, "unknown": 1})):
        with pytest.raises(turn.ResearchJudgmentError):
            turn.extract_closed_result(bad, turn.RESEARCH_JUDGMENT_PERSONA_TOOL)


def test_harness_env_is_derived_from_trusted_identity_only():
    endpoint = {"url": "http://mcp-readonly:8301/mcp/v1", "token": "ro"}
    identity = {field: field + "-value" for field in turn._IDENTITY_FIELDS}
    env = turn.build_read_only_harness_env(endpoint, identity)
    assert env["BYQ_MCP_READ_ONLY_URL"] == endpoint["url"]
    assert env["BYQ_MCP_READ_ONLY_TOKEN"] == endpoint["token"]
    assert env["BYQ_WORKSPACE_ID"] == "workspace_id-value"
    for missing in turn._IDENTITY_FIELDS:
        broken = dict(identity)
        broken.pop(missing)
        with pytest.raises(turn.ResearchJudgmentError):
            turn.build_read_only_harness_env(endpoint, broken)


def test_runner_uses_the_injected_harness_and_returns_the_closed_result():
    seen: list[str] = []
    text = json.dumps({"proposal": {"proposal_kind": "iteration_comparison"}})

    def fake_run(prompt: str):
        seen.append(prompt)
        return text

    runner = turn.DshBoundedTurnRunner(
        compatibility=object(),
        composition_path="/opt/byq/profiles/byq-research-judgment.patch.yml",
        identity={field: field + "-value" for field in turn._IDENTITY_FIELDS},
        provider="deepseek-official", model="deepseek-v4-flash",
        session_root="/tmp/home", session_id="p4-turn", environment={},
        run_harness=fake_run)
    result = runner({"stage_input": {"stage": "iteration_comparison"}},
                    turn.RESEARCH_JUDGMENT_PERSONA_TOOL)
    assert result == {"proposal": {"proposal_kind": "iteration_comparison"}}
    assert seen and turn.RESEARCH_JUDGMENT_PERSONA_TOOL in seen[0]


def test_composition_path_is_trusted_absolute():
    assert turn.resolve_judgment_composition({}) == turn.DEDICATED_COMPOSITION_PATH
    assert turn.resolve_judgment_composition(
        {"BYQ_JUDGMENT_COMPOSITION": "/opt/byq/x.patch.yml"}) == "/opt/byq/x.patch.yml"
    with pytest.raises(turn.ResearchJudgmentError):
        turn.resolve_judgment_composition({"BYQ_JUDGMENT_COMPOSITION": "relative/path.yml"})


def test_turn_module_keeps_the_compat_boundary():
    source = open(turn.__file__, encoding="utf-8").read()
    assert "deepseek_harness" not in source
    assert "notification.payload" not in source


def test_stage_judgment_entry_admits_runs_and_submits_server_derived_values():
    from app import research_judgment_entry as entry

    calls = []

    def transport(url, payload, headers, timeout):
        calls.append({"url": url, "payload": payload, "headers": headers})
        if url.endswith("/admit"):
            return {"call_identity": "turn-1", "call_index": 1, "model_call_limit": 2,
                    "stage": "backtest_analysis", "stage_input": {"stage": "backtest_analysis"}}
        return {"schema_version": "research-judgment-result-receipt.v1",
                "progress": {"continue": False}}

    built = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            built.update(kwargs)

        def __call__(self, admission, persona_tool):
            built["admission"] = admission
            return {"proposal": {"proposal_kind": "backtest_analysis"}}

    identity = {field: field + "-value" for field in entry._REQUIRED_IDENTITY}
    receipt = entry.run_stage_judgment(
        task_id="task_" + "a" * 32, call_identity="turn-1", backend_url="http://backend:8000",
        trusted_headers={"x-byq-workspace-id": "workspace_id-value"}, identity=identity,
        provider="deepseek-official", model="deepseek-v4-flash", session_root="/tmp/home",
        compatibility=object(), transport=transport, runner_factory=FakeRunner)
    assert receipt["schema_version"] == "research-judgment-result-receipt.v1"
    assert calls[0]["url"].endswith("/internal/research-judgment/task_" + "a" * 32 + "/admit")
    assert calls[1]["url"].endswith("/internal/research-judgment/task_" + "a" * 32 + "/result")
    assert calls[1]["payload"]["proposal"] == {"proposal_kind": "backtest_analysis"}
    # The entry derived identity/session from the trusted identity, not the caller.
    assert built["session_id"] == "session_id-value"
    assert built["identity"] == identity
    for missing in entry._REQUIRED_IDENTITY:
        broken = dict(identity)
        broken.pop(missing)
        with pytest.raises(ValueError):
            entry.run_stage_judgment(
                task_id="task_" + "a" * 32, call_identity="turn-1",
                backend_url="http://backend:8000", trusted_headers={}, identity=broken,
                provider="p", model="m", session_root="/tmp/home", compatibility=object(),
                transport=transport, runner_factory=FakeRunner)
