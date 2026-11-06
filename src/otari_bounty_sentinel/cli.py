"""CLI entrypoint for Otari Bounty Sentinel."""

from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from rich.console import Console
from otari_bounty_sentinel.auditor import OtariBountyAuditor, SAMPLE_BOUNTY_TARGETS
from otari_bounty_sentinel.gateway_client import OtariGatewayClient, normalize_otari_urls, resolve_nested_model_family
from otari_bounty_sentinel.guardrails_engine import OtariGuardrailsEvaluator
from otari_bounty_sentinel.mock_otari_gateway import running_local_otari_gateway

def run_end_to_end_showcase() -> dict[str, Any]:
    evaluator = OtariGuardrailsEvaluator()
    with running_local_otari_gateway(valid_api_key="tk-otari-devs-wilding-demo", max_budget_usd=5.00, initial_spent_usd=0.50) as server:
        with OtariGatewayClient(base_url=server.server_root, api_key="tk-otari-devs-wilding-demo") as client:
            auditor = OtariBountyAuditor(gateway_client=client, guardrails=evaluator)
            sol = SAMPLE_BOUNTY_TARGETS["SolidityBridgeVault.sol"]
            rep_sol = auditor.audit_target(target_name="SolidityBridgeVault.sol", code=sol["code"], language=sol["language"], file_path=sol["path"])
            server.failing_providers.add("anthropic")
            _, failover_tel = client.chat_completion(model="bounty-smart", messages=[{"role": "user", "content": "Verify failover"}])
            server.failing_providers.clear()
            server.spent_usd = 4.25
            py = SAMPLE_BOUNTY_TARGETS["PaymentWebhookHandler.py"]
            rep_py = auditor.audit_target(target_name="PaymentWebhookHandler.py", code=py["code"], language=py["language"], file_path=py["path"])
            g_sec = evaluator.evaluate(moment="pre_tool_use.read_target", target=".env.production")
            g_cmd = evaluator.evaluate(moment="pre_tool_use.command", target="git push --force origin main")
            g_stop = evaluator.evaluate(moment="stop.session", changed_paths=["src/otari_bounty_sentinel/auditor.py"], executed_commands=["pytest -q"])
            otlp_ok = evaluator.report_to_otari(g_sec, otari_url=server.server_root, api_key="tk-otari-devs-wilding-demo")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "normalized_urls_demo": normalize_otari_urls("https://api.otari.ai/api/v1"),
                "resolved_model_families_demo": {
                    "ollama:qwen2.5-coder:32b": resolve_nested_model_family("ollama:qwen2.5-coder:32b"),
                    "openrouter:deepseek/deepseek-r1": resolve_nested_model_family("openrouter:deepseek/deepseek-r1"),
                },
                "reports": [rep_sol.model_dump(), rep_py.model_dump()],
                "provider_failover_telemetry": failover_tel.model_dump(),
                "guardrails_verdicts": {
                    "secret_file_read": g_sec.model_dump(),
                    "destructive_command": g_cmd.model_dump(),
                    "stop_session_pytest_gate": g_stop.model_dump(),
                    "otlp_trace_exported": otlp_ok,
                    "otlp_batches_received": len(server.otlp_traces),
                },
            }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["demo", "json"], default="demo")
    parser.add_argument("--export-log", type=str, default="")
    args = parser.parse_args(argv)
    payload = run_end_to_end_showcase()
    if args.export_log:
        out = Path(args.export_log)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.mode == "json":
        print(json.dumps(payload, indent=2))
    else:
        Console().print_json(data=payload)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
