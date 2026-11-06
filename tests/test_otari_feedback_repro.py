"""Automated reproduction tests for Mozilla Otari (`mozilla-ai/otari`) DX & SDK findings."""

import httpx
from otari_bounty_sentinel.gateway_client import normalize_otari_urls, resolve_nested_model_family
from otari_bounty_sentinel.guardrails_engine import OtariGuardrailsEvaluator
from otari_bounty_sentinel.mock_otari_gateway import running_local_otari_gateway

def test_finding_1_otari_url_vs_otari_base_url_double_api_v1_path_bug() -> None:
    user_configured_url = "https://api.otari.ai/api/v1"
    naive_hook_url = f"{user_configured_url.rstrip('/')}/api/v1/hooks/guardrails"
    assert naive_hook_url == "https://api.otari.ai/api/v1/api/v1/hooks/guardrails"
    normalized = normalize_otari_urls(user_configured_url)
    assert normalized["hooks_guardrails_url"] == "https://api.otari.ai/api/v1/hooks/guardrails"

def test_finding_2_pydantic_ai_otari_model_profile_open_weight_fallback() -> None:
    assert resolve_nested_model_family("ollama:qwen2.5-coder:32b") == "qwen"
    assert resolve_nested_model_family("openrouter:deepseek/deepseek-r1") == "deepseek"
    assert resolve_nested_model_family("together:meta-llama/Llama-3.3-70B-Instruct") == "meta"

def test_finding_3_missing_api_prefix_returns_404_when_using_standard_v1_url() -> None:
    with running_local_otari_gateway(valid_api_key="tk-test") as server:
        assert httpx.get(f"{server.server_root}/v1/models").status_code == 404
        repaired = normalize_otari_urls(f"{server.server_root}/v1")
        assert httpx.get(f"{repaired['openai_base_url']}/models", headers={"Authorization": "Bearer tk-test"}).status_code == 200

def test_finding_4_guardrails_accept_warnings_and_root_dotenv_matching() -> None:
    evaluator = OtariGuardrailsEvaluator()
    gates_by_id = {g["id"]: g for g in evaluator.gates}
    assert "shell-read-unseen" in gates_by_id["no-secret-file-read-or-edit"]["accept_warnings"]
