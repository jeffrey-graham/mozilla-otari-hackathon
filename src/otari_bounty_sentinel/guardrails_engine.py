"""Mozilla Otari `.otari/guardrails/` Policy Evaluator & OTLP Reporter."""

from __future__ import annotations

import fnmatch
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from otari_bounty_sentinel.gateway_client import normalize_otari_urls
from otari_bounty_sentinel.schemas import GuardrailEvaluationResult, GuardrailGateVerdict

def _glob_matches_path(pattern: str, target_path: str) -> bool:
    norm_path = target_path.strip().lstrip("./")
    norm_pat = pattern.strip().lstrip("./")
    if fnmatch.fnmatch(norm_path, norm_pat):
        return True
    if norm_pat.startswith("**/") and fnmatch.fnmatch(norm_path, norm_pat[3:]):
        return True
    if norm_pat.endswith("/**"):
        prefix = norm_pat[:-3].rstrip("/")
        if norm_path == prefix or norm_path.startswith(prefix + "/"):
            return True
    return False

class OtariGuardrailsEvaluator:
    def __init__(self, policy_path: Path | None = None) -> None:
        if policy_path is None:
            policy_path = Path(__file__).resolve().parents[2] / ".otari" / "guardrails" / "bounty-sentinel.yml"
        self.policy_path = Path(policy_path)
        self.raw_spec: dict[str, Any] = yaml.safe_load(self.policy_path.read_text(encoding="utf-8"))
        self.policy_id = str(self.raw_spec.get("policy", {}).get("id", "otari-bounty-sentinel/default"))
        self.gates: list[dict[str, Any]] = list(self.raw_spec.get("gates", []))

    def evaluate(self, *, moment: str, target: str = "", changed_paths: list[str] | None = None, executed_commands: list[str] | None = None) -> GuardrailEvaluationResult:
        verdicts: list[GuardrailGateVerdict] = []
        any_blocked = False
        for gate in self.gates:
            gate_id = str(gate.get("id", "unnamed-gate"))
            gate_type = str(gate.get("type", "path"))
            runs = list(gate.get("runs", []))
            enforcement = str(gate.get("enforcement", "required"))
            message = str(gate.get("message", "Blocked by Otari Agent Guardrail."))
            if moment not in runs:
                continue
            failed = False
            if gate_type == "path":
                failed = any(_glob_matches_path(str(g), target) for g in gate.get("forbidden", []))
            elif gate_type == "command":
                lowered_cmd = target.lower()
                failed = any(str(p).lower() in lowered_cmd for p in gate.get("forbidden", []))
            elif gate_type == "command_if_changed":
                when_changed = [str(g) for g in gate.get("when_changed", [])]
                required_cmds = [str(r).lower() for r in gate.get("require", [])]
                paths = changed_paths or ([target] if target else [])
                cmds = [c.lower() for c in (executed_commands or [])]
                if any(_glob_matches_path(g, p) for g in when_changed for p in paths):
                    failed = not any(req in cmd for req in required_cmds for cmd in cmds)
            blocked = bool(failed and enforcement == "required")
            if blocked:
                any_blocked = True
            verdicts.append(GuardrailGateVerdict(
                gate_id=gate_id, gate_type=gate_type, moment=moment,
                enforcement=enforcement, outcome="fail" if failed else "pass",
                blocked=blocked, message=message if failed else f"Gate '{gate_id}' passed.",
            ))
        return GuardrailEvaluationResult(policy_id=self.policy_id, moment=moment, target_evidence=target, blocked=any_blocked, verdicts=verdicts)

    def report_to_otari(self, result: GuardrailEvaluationResult, *, otari_url: str, api_key: str, session_id: str = "sentinel-guardrail-session") -> bool:
        urls = normalize_otari_urls(otari_url)
        now_ns = int(time.time() * 1e9)
        trace_id = secrets.token_hex(16)
        spans = [{
            "traceId": trace_id, "spanId": secrets.token_hex(8), "name": "otari.gate", "kind": 1,
            "startTimeUnixNano": str(now_ns - 1_000_000), "endTimeUnixNano": str(now_ns),
            "attributes": [
                {"key": "session.id", "value": {"stringValue": session_id}},
                {"key": "otari.policy.id", "value": {"stringValue": result.policy_id}},
                {"key": "otari.gate.id", "value": {"stringValue": v.gate_id}},
                {"key": "otari.gate.outcome", "value": {"stringValue": v.outcome}},
                {"key": "otari.gate.blocked", "value": {"boolValue": v.blocked}},
            ],
        } for v in result.verdicts]
        body = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "otari-bounty-sentinel"}}]}, "scopeSpans": [{"scope": {"name": "otari.hook"}, "spans": spans}]}]}
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(urls["otlp_traces_url"], json=body, headers={"Authorization": f"Bearer {api_key}"})
            return resp.status_code == 200
