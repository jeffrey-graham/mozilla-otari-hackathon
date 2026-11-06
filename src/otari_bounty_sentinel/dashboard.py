"""FastAPI Web Dashboard & REST API for Otari Bounty Sentinel."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from otari_bounty_sentinel.auditor import OtariBountyAuditor, SAMPLE_BOUNTY_TARGETS
from otari_bounty_sentinel.gateway_client import OtariGatewayClient
from otari_bounty_sentinel.guardrails_engine import OtariGuardrailsEvaluator
from otari_bounty_sentinel.schemas import BountyAuditReport, GuardrailEvaluationResult, OtariKeyBudgetStatus

class AuditRequestPayload(BaseModel):
    target_name: str = "SolidityBridgeVault.sol"
    code: str | None = None
    language: str = "solidity"
    file_path: str = "contracts/SolidityBridgeVault.sol"

class GuardrailEvalRequestPayload(BaseModel):
    moment: str = "pre_tool_use.read_target"
    target: str = ".env.production"
    changed_paths: list[str] = []
    executed_commands: list[str] = []

DASHBOARD_HTML = "<html><body><h1>Otari Bounty Sentinel</h1></body></html>"

def create_dashboard_app(gateway_client: OtariGatewayClient, guardrails_evaluator: OtariGuardrailsEvaluator | None = None) -> FastAPI:
    evaluator = guardrails_evaluator or OtariGuardrailsEvaluator()
    auditor = OtariBountyAuditor(gateway_client=gateway_client, guardrails=evaluator)
    app = FastAPI(title="Otari Bounty Sentinel Dashboard", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "otari-bounty-sentinel", "otari_openai_base_url": gateway_client.base_url, "guardrails_policy_id": evaluator.policy_id}

    @app.get("/api/budget", response_model=OtariKeyBudgetStatus)
    def get_budget() -> OtariKeyBudgetStatus:
        return gateway_client.get_key_budget()

    @app.get("/api/samples")
    def get_samples() -> dict[str, Any]:
        return SAMPLE_BOUNTY_TARGETS

    @app.post("/api/audit", response_model=BountyAuditReport)
    def run_audit(payload: AuditRequestPayload) -> BountyAuditReport:
        sample = SAMPLE_BOUNTY_TARGETS.get(payload.target_name)
        code = payload.code or (sample["code"] if sample else "")
        language = sample["language"] if (sample and payload.code is None) else payload.language
        file_path = sample["path"] if (sample and payload.code is None) else payload.file_path
        if not code.strip():
            raise HTTPException(status_code=400, detail="Target code must not be empty.")
        try:
            return auditor.audit_target(target_name=payload.target_name, code=code, language=language, file_path=file_path)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/guardrails/evaluate", response_model=GuardrailEvaluationResult)
    def evaluate_guardrails(payload: GuardrailEvalRequestPayload) -> GuardrailEvaluationResult:
        return evaluator.evaluate(moment=payload.moment, target=payload.target, changed_paths=payload.changed_paths, executed_commands=payload.executed_commands)

    @app.get("/api/config/otari-yaml", response_class=PlainTextResponse)
    def get_otari_config_yaml() -> str:
        return (Path(__file__).resolve().parents[2] / "config.otari.example.yml").read_text(encoding="utf-8")

    return app
