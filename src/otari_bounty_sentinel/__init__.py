"""Otari Bounty Sentinel: Multi-LLM Code Audit & Bounty Triage powered by Mozilla Otari."""

from otari_bounty_sentinel.auditor import OtariBountyAuditor
from otari_bounty_sentinel.gateway_client import (
    OtariGatewayClient,
    normalize_otari_urls,
    resolve_nested_model_family,
)
from otari_bounty_sentinel.guardrails_engine import OtariGuardrailsEvaluator
from otari_bounty_sentinel.schemas import (
    BountyAuditReport,
    BountyFinding,
    GuardrailEvaluationResult,
    OtariKeyBudgetStatus,
    OtariRouteTelemetry,
)

__all__ = [
    "BountyAuditReport",
    "BountyFinding",
    "GuardrailEvaluationResult",
    "OtariBountyAuditor",
    "OtariGatewayClient",
    "OtariGuardrailsEvaluator",
    "OtariKeyBudgetStatus",
    "OtariRouteTelemetry",
    "normalize_otari_urls",
    "resolve_nested_model_family",
]

__version__ = "0.1.0"
