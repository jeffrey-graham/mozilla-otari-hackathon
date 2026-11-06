"""Unified Mozilla Otari Gateway Client + URL & Model Profile Normalizers."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx

from otari_bounty_sentinel.schemas import OtariKeyBudgetStatus, OtariRouteTelemetry

DEFAULT_OTARI_SERVER_ROOT = "https://api.otari.ai"

KNOWN_MODEL_FAMILIES: tuple[str, ...] = (
    "qwen", "deepseek", "claude", "anthropic", "llama", "meta", "mistral",
    "codestral", "gemini", "google", "gemma", "grok", "xai", "cohere",
    "command-r", "moonshot", "kimi", "gpt", "o1", "o3", "o4", "openai",
)

FAMILY_CANONICAL_MAP: dict[str, str] = {
    "qwen": "qwen", "deepseek": "deepseek", "claude": "anthropic",
    "anthropic": "anthropic", "llama": "meta", "meta": "meta",
    "mistral": "mistral", "codestral": "mistral", "gemini": "google",
    "google": "google", "gemma": "google", "grok": "xai", "xai": "xai",
    "cohere": "cohere", "command-r": "cohere", "moonshot": "moonshotai",
    "kimi": "moonshotai", "gpt": "openai", "o1": "openai", "o3": "openai",
    "o4": "openai", "openai": "openai",
}

def normalize_otari_urls(raw_url: str | None = None) -> dict[str, str]:
    candidate = (
        (raw_url or "").strip()
        or os.getenv("OTARI_BASE_URL", "").strip()
        or os.getenv("OTARI_URL", "").strip()
        or DEFAULT_OTARI_SERVER_ROOT
    ).rstrip("/")
    for suffix in ("/api/v1", "/api", "/v1", "/otlp/v1/traces", "/otlp"):
        if candidate.lower().endswith(suffix):
            candidate = candidate[: -len(suffix)].rstrip("/")
            break
    server_root = candidate or DEFAULT_OTARI_SERVER_ROOT
    return {
        "server_root": server_root,
        "openai_base_url": f"{server_root}/api/v1",
        "anthropic_base_url": f"{server_root}/api",
        "otlp_traces_url": f"{server_root}/otlp/v1/traces",
        "hooks_guardrails_url": f"{server_root}/api/v1/hooks/guardrails",
        "external_events_url": f"{server_root}/api/v1/usage/external-events",
    }

def resolve_nested_model_family(model_name: str) -> str:
    lowered = (model_name or "").strip().lower()
    if not lowered:
        return "openai"
    provider, sep, remainder = lowered.partition(":")
    if not sep:
        provider, sep, remainder = lowered.partition("/")
    if provider in FAMILY_CANONICAL_MAP:
        return FAMILY_CANONICAL_MAP[provider]
    search_space = remainder if sep else lowered
    for token in KNOWN_MODEL_FAMILIES:
        if token in search_space:
            return FAMILY_CANONICAL_MAP[token]
    return "openai"

class OtariGatewayClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout_seconds: float = 30.0) -> None:
        resolved_key = (api_key or os.getenv("OTARI_API_KEY") or "").strip()
        if not resolved_key:
            raise ValueError("Set OTARI_API_KEY or pass api_key.")
        self.api_key = resolved_key
        self.urls = normalize_otari_urls(base_url)
        self.base_url = self.urls["openai_base_url"]
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Otari-Key": self.api_key,
                "Content-Type": "application/json",
            },
        )
        self.telemetry_history: list[OtariRouteTelemetry] = []

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OtariGatewayClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_key_budget(self) -> OtariKeyBudgetStatus:
        resp = self._client.get(f"{self.base_url}/key")
        resp.raise_for_status()
        return OtariKeyBudgetStatus(**resp.json())

    def list_models(self) -> list[str]:
        resp = self._client.get(f"{self.base_url}/models")
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("data", payload) if isinstance(payload, dict) else payload
        return [str(m.get("id")) for m in items if isinstance(m, dict) and m.get("id")]

    def chat_completion(self, *, model: str, messages: list[dict[str, str]], fallback_models: list[str] | None = None, temperature: float = 0.1) -> tuple[dict[str, Any], OtariRouteTelemetry]:
        started = time.perf_counter()
        budget_status = self.get_key_budget()
        effective_model = model
        budget_downgraded = False
        if budget_status.budget_used_pct >= 80.0 and model in {"bounty-smart", "anthropic:claude-sonnet-4-6", "openai:gpt-4o"}:
            effective_model = "bounty-smart" if model == "bounty-smart" else "ollama:qwen2.5-coder:32b"
            budget_downgraded = True
        candidates = [effective_model]
        for fb in fallback_models or []:
            if fb not in candidates:
                candidates.append(fb)
        attempted: list[str] = []
        last_error: Exception | None = None
        for idx, candidate_model in enumerate(candidates):
            attempted.append(candidate_model)
            try:
                resp = self._client.post(f"{self.base_url}/chat/completions", json={"model": candidate_model, "messages": messages, "temperature": temperature})
                if resp.status_code >= 400:
                    raise httpx.HTTPStatusError(f"Otari error {resp.status_code}", request=resp.request, response=resp)
                payload = resp.json()
                elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
                usage = payload.get("usage") or {}
                otari_meta = payload.get("otari_meta") or {}
                resolved_model = str(otari_meta.get("resolved_model") or resp.headers.get("x-otari-routed-model") or payload.get("model") or candidate_model)
                gateway_attempts = otari_meta.get("attempted_models") or attempted
                telemetry = OtariRouteTelemetry(
                    request_id=str(payload.get("id") or f"req-{uuid.uuid4().hex[:8]}"),
                    requested_policy_or_model=model,
                    resolved_model=resolved_model,
                    attempted_models=list(gateway_attempts),
                    failover_triggered=bool(idx > 0 or otari_meta.get("failover_triggered", False) or len(gateway_attempts) > 1),
                    budget_downgrade_triggered=bool(budget_downgraded or otari_meta.get("budget_downgrade_triggered", False)),
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    cost_usd=float(otari_meta.get("cost_usd", 0.0)),
                    latency_ms=elapsed_ms,
                )
                self.telemetry_history.append(telemetry)
                return payload, telemetry
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"All Otari model candidates {attempted} failed: {last_error}") from last_error
