"""Pydantic v2 models for Otari Bounty Sentinel."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

SeverityType = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

class OtariKeyBudgetStatus(BaseModel):
    key_name: str = "bounty-sentinel-key"
    user_id: str = "mozfest-hacker"
    max_budget_usd: float = 5.0
    spent_usd: float = 0.0
    budget_remaining_usd: float = 5.0
    budget_used_pct: float = 0.0
    allowed_models: list[str] = Field(default_factory=list)

class OtariRouteTelemetry(BaseModel):
    request_id: str
    requested_policy_or_model: str
    resolved_model: str
    attempted_models: list[str] = Field(default_factory=list)
    failover_triggered: bool = False
    budget_downgrade_triggered: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

class BountyFinding(BaseModel):
    rule_id: str
    title: str
    severity: SeverityType
    cwe_or_swc: str
    cvss_score: float = Field(..., ge=0.0, le=10.0)
    estimated_bounty_usd: int
    evidence_snippet: str
    remediation_diff: str
    confirmed_by_models: list[str] = Field(default_factory=list)

class BountyAuditReport(BaseModel):
    target_name: str
    language: str
    overall_severity: SeverityType
    risk_score: int = Field(..., ge=0, le=100)
    consensus_confidence: float = Field(..., ge=0.0, le=1.0)
    total_estimated_bounty_usd: int
    findings: list[BountyFinding]
    route_telemetry: list[OtariRouteTelemetry]
    key_budget_after: OtariKeyBudgetStatus
    guardrails_passed: bool = True
    summary: str

class GuardrailGateVerdict(BaseModel):
    gate_id: str
    gate_type: str
    moment: str
    enforcement: str
    outcome: Literal["pass", "fail", "skipped"]
    blocked: bool
    message: str

class GuardrailEvaluationResult(BaseModel):
    policy_id: str
    moment: str
    target_evidence: str
    blocked: bool
    verdicts: list[GuardrailGateVerdict]
