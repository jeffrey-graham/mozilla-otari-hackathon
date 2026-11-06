"""End-to-end test suite for Otari Bounty Sentinel."""

from pathlib import Path
from fastapi.testclient import TestClient
from otari_bounty_sentinel.cli import main as cli_main
from otari_bounty_sentinel.dashboard import create_dashboard_app
from otari_bounty_sentinel.gateway_client import OtariGatewayClient, normalize_otari_urls, resolve_nested_model_family
from otari_bounty_sentinel.guardrails_engine import OtariGuardrailsEvaluator
from otari_bounty_sentinel.mock_otari_gateway import running_local_otari_gateway

def test_normalize_otari_urls_bridges_all_suffixes() -> None:
    for raw in ("https://api.otari.ai", "https://api.otari.ai/api/v1", "https://api.otari.ai/api", "https://api.otari.ai/v1"):
        urls = normalize_otari_urls(raw)
        assert urls["server_root"] == "https://api.otari.ai"
        assert urls["openai_base_url"] == "https://api.otari.ai/api/v1"
        assert urls["hooks_guardrails_url"] == "https://api.otari.ai/api/v1/hooks/guardrails"

def test_resolve_nested_model_family_for_open_weight_gateways() -> None:
    assert resolve_nested_model_family("ollama:qwen2.5-coder:32b") == "qwen"
    assert resolve_nested_model_family("openrouter:deepseek/deepseek-r1") == "deepseek"
    assert resolve_nested_model_family("together:meta-llama/Llama-3.3-70B") == "meta"

def test_gateway_routing_failover_and_budget_downgrade() -> None:
    with running_local_otari_gateway(valid_api_key="tk-test-key", max_budget_usd=10.0, initial_spent_usd=1.0) as server:
        with OtariGatewayClient(base_url=server.api_v1_url, api_key="tk-test-key") as client:
            _, tel_normal = client.chat_completion(model="bounty-smart", messages=[{"role": "user", "content": "Audit"}])
            assert tel_normal.resolved_model == "anthropic:claude-sonnet-4-6"
            server.failing_providers.add("anthropic")
            _, tel_fo = client.chat_completion(model="bounty-smart", messages=[{"role": "user", "content": "Audit"}])
            assert tel_fo.resolved_model == "ollama:qwen2.5-coder:32b"
            assert tel_fo.failover_triggered is True
            server.failing_providers.clear()
            server.spent_usd = 8.50
            _, tel_budget = client.chat_completion(model="bounty-smart", messages=[{"role": "user", "content": "Audit"}])
            assert tel_budget.resolved_model == "ollama:qwen2.5-coder:32b"
            assert tel_budget.budget_downgrade_triggered is True

def test_guardrails_evaluator_and_otlp_export() -> None:
    evaluator = OtariGuardrailsEvaluator()
    assert evaluator.evaluate(moment="pre_tool_use.read_target", target=".env.production").blocked is True
    assert evaluator.evaluate(moment="pre_tool_use.command", target="git push --force origin main").blocked is True

def test_auditor_and_fastapi_dashboard_endpoints() -> None:
    with running_local_otari_gateway(valid_api_key="tk-dashboard-key") as server:
        with OtariGatewayClient(base_url=server.server_root, api_key="tk-dashboard-key") as client:
            http = TestClient(create_dashboard_app(gateway_client=client))
            assert http.get("/api/health").json()["status"] == "ok"
            assert http.post("/api/audit", json={"target_name": "SolidityBridgeVault.sol"}).status_code == 200

def test_cli_json_export(tmp_path: Path) -> None:
    out_file = tmp_path / "execution.json"
    assert cli_main(["--mode", "json", "--export-log", str(out_file)]) == 0
    assert out_file.exists()
