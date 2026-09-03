from importlib.metadata import version
from pathlib import Path

from deepseek_harness import HarnessClient, Notification


def test_installed_official_sdk_pair_is_exact_rc1() -> None:
    assert version("deepseek-harness-sdk") == "0.1.1rc1"
    assert version("deepseek-harness-runtime-bin") == "0.1.1rc1"


def test_runtime_uses_public_rc1_jsonrpc_agent_bin() -> None:
    from app.runtime import RuntimeAdapter

    assert RuntimeAdapter().runtime_command[1].endswith(
        "@deepseek-ai/dsh-sdk-jsonrpc-demo/lib/bin.js"
    )


def test_sdk_session_tree_filter_delivers_subagent_lifecycle_and_descendants() -> None:
    client = HarnessClient()
    client._session_parents["child-1"] = "root-1"
    belongs = client._notification_belongs_to_session_tree("root-1")

    assert belongs(Notification(
        method="subagent.finished",
        payload={"parentSessionId": "root-1", "childSessionId": "child-1"},
    ))
    assert belongs(Notification(method="session.status", payload={"sessionId": "child-1"}))
    assert not belongs(Notification(method="session.status", payload={"sessionId": "other"}))


def test_product_composition_contains_jsonrpc_and_byq_mcp_without_coding() -> None:
    candidates = [Path("/opt/byq/compositions/byq-product-sdk.cordis.yml")]
    candidates.extend(
        parent / "plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml"
        for parent in Path(__file__).resolve().parents
    )
    composition = next(path for path in candidates if path.is_file())
    contents = composition.read_text()
    assert "@deepseek-ai/dsh-sdk-jsonrpc-server" in contents
    assert "@deepseek-ai/dsh-mcp-client" in contents
    assert "@deepseek-ai/dsh-session-checkpoint-policy" in contents
    assert "@deepseek-ai/dsh-session-persistence-jsonl" in contents
    assert "@deepseek-ai/dsh-llm-pi-ai" in contents
    assert "https://opencode.ai/zen/go/v1" in contents
    assert "https://opencode.ai/zen/v1" in contents
    assert contents.count("apiKeyEnv: OPENCODE_API_KEY") == 6
    assert "baseURL: !!js" not in contents
    assert "toolBash: false" in contents
    assert "toolJobs: false" in contents
    assert "enabled: false" in contents
    assert "tool-bash" not in contents
    assert "terminal" not in contents


def test_product_research_skill_requires_evidence_bound_public_answers() -> None:
    skill_roots = [Path("/opt/dsh/bundles/dsh-byq/skills")]
    skill_roots.extend(
        parent / "plugins/dsh-byq/skills" for parent in Path(__file__).resolve().parents
    )
    skill_root = next(path for path in skill_roots if path.is_dir())
    role_contract = (skill_root / "byq-role-contracts/SKILL.md").read_text()
    market_contract = (skill_root / "byq-market-researcher/SKILL.md").read_text()
    product_guide = (skill_root / "byq-product-guide/SKILL.md").read_text()
    ml_contract = (skill_root / "byq-ml-researcher/SKILL.md").read_text()
    feedback_contract = (skill_root / "byq-product-feedback/SKILL.md").read_text()

    assert "Do not write a preface" in role_contract
    assert "unqueried or unavailable profitability" in role_contract
    assert "cause is not established by the available data" in market_contract
    assert "performs no domain write" in role_contract
    assert "It creates no ResearchTask" in role_contract
    assert "temporary trend or comparison request creates no" in market_contract
    assert "byq_product_help_query" in product_guide
    assert "do not start a domain AgentRun" in product_guide
    assert "Product help never authorizes" in product_guide
    assert "最近 N 个交易日" in market_contract
    assert "last_close / first_pre_close - 1" in market_contract
    assert "last_close / first_close - 1" in market_contract
    assert "首日至末日" in market_contract
    assert "newest listed session" in market_contract
    assert "byq_ml_capabilities" in ml_contract
    assert "never create or decide that" in ml_contract
    assert "byq_ml_prediction_create" in ml_contract
    assert "Only the derived ML backtest task" in ml_contract
    assert "Do not call submit in this turn" in feedback_contract
    assert "Never request a GitHub account" in feedback_contract
