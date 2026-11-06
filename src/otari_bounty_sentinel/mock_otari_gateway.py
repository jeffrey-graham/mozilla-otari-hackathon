"""Embedded Mozilla Otari Gateway Server Simulator (`/api/v1/*`, `/otlp/v1/traces`)."""

from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

MODEL_CATALOG: dict[str, dict[str, Any]] = {
    "anthropic:claude-sonnet-4-6": {"provider": "anthropic", "open_weight": False, "input_price_per_m": 3.00, "output_price_per_m": 15.00},
    "openai:gpt-4o-mini": {"provider": "openai", "open_weight": False, "input_price_per_m": 0.15, "output_price_per_m": 0.60},
    "ollama:qwen2.5-coder:32b": {"provider": "ollama", "open_weight": True, "input_price_per_m": 0.05, "output_price_per_m": 0.15},
    "ollama:deepseek-r1:14b": {"provider": "ollama", "open_weight": True, "input_price_per_m": 0.04, "output_price_per_m": 0.12},
}

class LocalOtariGatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *, valid_api_key: str = "tk-otari-devs-wilding-demo", max_budget_usd: float = 5.00, initial_spent_usd: float = 0.40, failing_providers: set[str] | None = None) -> None:
        super().__init__(("127.0.0.1", 0), _OtariGatewayHandler)
        self.valid_api_key = valid_api_key
        self.max_budget_usd = max_budget_usd
        self.spent_usd = initial_spent_usd
        self.failing_providers: set[str] = set(failing_providers or set())
        self.requests_log: list[dict[str, Any]] = []
        self.guardrail_definitions: list[dict[str, Any]] = []
        self.otlp_traces: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @property
    def server_root(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def api_v1_url(self) -> str:
        return f"{self.server_root}/api/v1"

    def budget_status(self) -> dict[str, Any]:
        with self._lock:
            remaining = max(0.0, round(self.max_budget_usd - self.spent_usd, 6))
            used_pct = round((self.spent_usd / self.max_budget_usd) * 100.0, 2) if self.max_budget_usd > 0 else 100.0
            return {
                "key_name": "bounty-sentinel-key",
                "user_id": "mozfest-hacker",
                "max_budget_usd": self.max_budget_usd,
                "spent_usd": round(self.spent_usd, 6),
                "budget_remaining_usd": remaining,
                "budget_used_pct": min(100.0, used_pct),
                "allowed_models": list(MODEL_CATALOG.keys()) + ["bounty-smart", "openweight-consensus"],
            }

    def resolve_routing_policy(self, requested_model: str) -> tuple[str, list[str], bool, bool]:
        status = self.budget_status()
        used_pct = status["budget_used_pct"]
        budget_downgrade = False
        if requested_model == "bounty-smart":
            if used_pct >= 80.0:
                primary = "ollama:qwen2.5-coder:32b"
                budget_downgrade = True
            else:
                primary = "anthropic:claude-sonnet-4-6"
            fallbacks = ["ollama:qwen2.5-coder:32b", "openai:gpt-4o-mini"]
        elif requested_model == "openweight-consensus":
            primary = "ollama:qwen2.5-coder:32b"
            fallbacks = ["ollama:deepseek-r1:14b", "openai:gpt-4o-mini"]
        else:
            primary = requested_model
            fallbacks = ["ollama:qwen2.5-coder:32b"]
        candidates = [primary] + [m for m in fallbacks if m != primary]
        attempted: list[str] = []
        for idx, candidate in enumerate(candidates):
            attempted.append(candidate)
            if candidate.split(":")[0] in self.failing_providers:
                continue
            return candidate, attempted, (idx > 0), budget_downgrade
        raise RuntimeError(f"All candidates failed for policy {requested_model}: {attempted}")

    def record_spend(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        rates = MODEL_CATALOG.get(model, {"input_price_per_m": 0.10, "output_price_per_m": 0.30})
        cost = round(max((prompt_tokens / 1e6) * float(rates["input_price_per_m"]) + (completion_tokens / 1e6) * float(rates["output_price_per_m"]), 0.0001), 6)
        with self._lock:
            self.spent_usd = round(self.spent_usd + cost, 6)
        return cost

class _OtariGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: LocalOtariGatewayServer

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        otari_key = self.headers.get("Otari-Key", "")
        token = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else otari_key.replace("Bearer ", "").strip()
        if token != self.server.valid_api_key:
            self._send_json(401, {"detail": "Invalid or missing Otari API key"})
            return False
        return True

    def do_GET(self) -> None:
        if self.path == "/api/v1/health":
            self._send_json(200, {"status": "healthy", "service": "otari-gateway"})
            return
        if self.path.startswith("/v1/"):
            self._send_json(404, {"detail": f"Route {self.path} not found. Did you mean /api{self.path}? See docs/api-reference.md."})
            return
        if not self._check_auth():
            return
        if self.path == "/api/v1/key":
            self._send_json(200, self.server.budget_status())
            return
        if self.path == "/api/v1/models":
            self._send_json(200, {"object": "list", "data": [{"id": m_id, "object": "model", **meta} for m_id, meta in MODEL_CATALOG.items()]})
            return
        self._send_json(404, {"detail": f"Not found: {self.path}"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        body = json.loads(raw.decode("utf-8", errors="replace") or "{}")
        if self.path.startswith("/v1/"):
            self._send_json(404, {"detail": f"Route {self.path} not found. Use /api{self.path}."})
            return
        if self.path == "/otlp/v1/traces":
            with self.server._lock:
                self.server.otlp_traces.append(body)
            self._send_json(200, {"partialSuccess": {}})
            return
        if not self._check_auth():
            return
        if self.path == "/api/v1/hooks/guardrails":
            with self.server._lock:
                self.server.guardrail_definitions.append(body)
            self._send_json(200, {"status": "registered"})
            return
        if self.path == "/api/v1/chat/completions":
            status = self.server.budget_status()
            if status["budget_remaining_usd"] <= 0:
                self._send_json(402, {"detail": "Budget ceiling exceeded for this Otari virtual key."})
                return
            requested_model = str(body.get("model") or "bounty-smart")
            try:
                resolved_model, attempted, failover, downgraded = self.server.resolve_routing_policy(requested_model)
            except RuntimeError as exc:
                self._send_json(502, {"detail": str(exc)})
                return
            cost_usd = self.server.record_spend(resolved_model, 240, 160)
            req_id = f"otari-cmpl-{uuid.uuid4().hex[:8]}"
            reply_content = json.dumps({"auditor_model": resolved_model, "verdict": "CONFIRMED_VULNERABLE", "confidence": 0.94})
            response_payload = {
                "id": req_id, "object": "chat.completion", "created": int(time.time()), "model": requested_model,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": reply_content}}],
                "usage": {"prompt_tokens": 240, "completion_tokens": 160, "total_tokens": 400},
                "otari_meta": {"resolved_model": resolved_model, "attempted_models": attempted, "failover_triggered": failover, "budget_downgrade_triggered": downgraded, "cost_usd": cost_usd},
            }
            with self.server._lock:
                self.server.requests_log.append({"request": body, "response": response_payload})
            self._send_json(200, response_payload, extra_headers={"x-otari-routed-model": resolved_model})
            return
        self._send_json(404, {"detail": f"Unknown route {self.path}"})

    def _send_json(self, status: int, payload: dict[str, Any], extra_headers: dict[str, str] | None = None) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return

@contextmanager
def running_local_otari_gateway(*, valid_api_key: str = "tk-otari-devs-wilding-demo", max_budget_usd: float = 5.00, initial_spent_usd: float = 0.40, failing_providers: set[str] | None = None) -> Iterator[LocalOtariGatewayServer]:
    server = LocalOtariGatewayServer(valid_api_key=valid_api_key, max_budget_usd=max_budget_usd, initial_spent_usd=initial_spent_usd, failing_providers=failing_providers)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3.0)
