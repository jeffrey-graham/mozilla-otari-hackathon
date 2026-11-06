# Mozilla Otari (`mozilla-ai/otari`) Developer Experience, SDK, and Guardrails Feedback Report

**Hackathon:** Mozilla Otari Hackathon — Devs Wilding Online! (`https://dorahacks.io/hackathon/mozilla-devs-wilding/detail`)  
**Project:** **Otari Bounty Sentinel** — Budget-Aware Multi-LLM Security Auditor & Guardrail Engine  
**Evaluated Upstream Repository:** `https://github.com/mozilla-ai/otari` (`otari-agent`, `pydantic-ai-otari`, `langchain-otari`, and gateway documentation)

All findings below are accompanied by automated reproduction tests in [`tests/test_otari_feedback_repro.py`](tests/test_otari_feedback_repro.py) and drop-in fixes implemented in [`src/otari_bounty_sentinel/gateway_client.py`](src/otari_bounty_sentinel/gateway_client.py).

---

## Executive Summary of Findings

| ID | Component | Severity | Summary |
| :--- | :--- | :--- | :--- |
| **OTARI-01** | `pydantic-ai-otari` / `langchain-otari` vs `otari_agent` (`report.py`, `usage_import.py`) | **High (DX / 404 Bug)** | Split environment variables (`OTARI_BASE_URL` vs `OTARI_URL`) and inconsistent path suffixes (`/api/v1`, `/api`, bare root) cause `/api/v1/api/v1/hooks/guardrails` 404s when developers reuse the same URL across SDKs and CLI hooks. |
| **OTARI-02** | `integrations/pydantic-ai-otari/src/pydantic_ai_otari/__init__.py` (`lines 48-64, 108-116`) | **Medium (Open-Weight Routing)** | `OtariProvider.model_profile()` only inspects the outer provider prefix before `:` or `/`. Open-weight models routed via `ollama:qwen2.5-coder:32b`, `openrouter:deepseek/deepseek-r1`, `together:meta-llama/...`, or routing policy names (`bounty-smart`) miss `_PROFILES` and fall back to generic `openai_model_profile`. |
| **OTARI-03** | `integrations/pydantic-ai-otari/src/pydantic_ai_otari/__init__.py` (`lines 92-94`) | **Medium (SDK Silent Misroute)** | Passing a custom `openai_client` to `OtariProvider(openai_client=...)` bypasses `OTARI_API_KEY` validation and `OTARI_BASE_URL` injection, silently sending requests to `api.openai.com/v1` unless the caller manually configured `base_url`. |
| **OTARI-04** | `cli/pyproject.toml` (`lines 9, 43`) | **Medium (Packaging / Adoption)** | `otari-agent` declares `requires-python = ">=3.13"` and `requires = ["setuptools>=84.2.1", "setuptools-scm>=10.3.4"]`, blocking `pip`/`uv` installation on Python 3.11 and 3.12 (including Ubuntu 24.04 LTS default Python 3.12) even though `cli/src/otari_agent/` uses only Python 3.11+ standard syntax. |
| **OTARI-05** | Gateway `/api/v1/chat/completions` & `docs/routing.md` (`lines 204-230`) | **Medium (Observability)** | When a routing policy (`bounty-smart`) or `on_failure` fallback executes, standard OpenAI chat completion payloads do not standardize `x-otari-routed-model` or `otari_meta.attempted_models` for downstream SDK inspection, and `when: { budget_used_pct: ... }` is silently skipped if a budget ceiling is provider-scoped. |
| **OTARI-06** | `cli/src/otari_agent/domain/validation.py` (`lines 69-145`) | **Low-Medium (Guardrails UX)** | `otari guardrails validate` treats lint warnings (`shell-write-unseen`, `shell-read-unseen`, `single-token-phrase`, `glob-matches-no-file`) as non-zero failures unless suppressed in `accept_warnings`, which surprises first-time authors writing `.otari/guardrails/*.yml`. |
| **OTARI-07** | `docs/api-reference.md` (`/v1/*` vs `/api/v1/*`) | **Low (Onboarding Friction)** | Standard OpenAI SDKs append `/chat/completions` to `https://api.openai.com/v1`. Pointing an OpenAI client at `https://api.otari.ai/v1` returns 404 because Otari mounts OpenAI routes at `/api/v1` while Anthropic routes live at `/api`. |

---

## Detailed Findings & Upstream Patch Proposals

### Finding OTARI-01: Environment Variable & URL Path Split (`OTARI_BASE_URL` vs `OTARI_URL`)
- **Upstream Locations:** `integrations/pydantic-ai-otari/src/pydantic_ai_otari/__init__.py:38, 100`, `integrations/langchain-otari/src/langchain_otari/chat_models.py:31, 90`, `cli/src/otari_agent/report.py:130, 346`, `cli/src/otari_agent/usage_import.py:216`
- **Suggested Upstream Fix:** Add a shared URL normalizer (implemented in [`normalize_otari_urls()`](src/otari_bounty_sentinel/gateway_client.py#L75-L100)) that accepts either `OTARI_BASE_URL` or `OTARI_URL`, strips any trailing `/api/v1`, `/api`, or `/v1`, and derives canonical URLs for OpenAI (`/api/v1`), Anthropic (`/api`), OTLP (`/otlp/v1/traces`), and Guardrail hooks (`/api/v1/hooks/guardrails`).

### Finding OTARI-02: `pydantic_ai_otari.OtariProvider.model_profile()` Ignores Nested Open-Weight Model Families
- **Upstream Location:** `integrations/pydantic-ai-otari/src/pydantic_ai_otari/__init__.py:48-64, 108-116`
- **Suggested Upstream Fix:** When `provider.lower()` is not in `_PROFILES`, inspect `model_id.lower()` for known model family tokens (`qwen`, `deepseek`, `llama`, `mistral`, `gemma`, `kimi`, `claude`), as implemented in [`resolve_nested_model_family()`](src/otari_bounty_sentinel/gateway_client.py#L103-L126).

### Finding OTARI-03: `OtariProvider(openai_client=...)` Skips `OTARI_BASE_URL` Verification
- **Upstream Location:** `integrations/pydantic-ai-otari/src/pydantic_ai_otari/__init__.py:92-94`
- **Suggested Upstream Fix:** If `str(openai_client.base_url).rstrip("/") == "https://api.openai.com/v1"`, override `openai_client.base_url` with `base_url or os.getenv("OTARI_BASE_URL") or DEFAULT_BASE_URL`.

### Finding OTARI-04: `otari-agent` `requires-python = ">=3.13"` Blocks Python 3.11 & 3.12 Environments
- **Upstream Location:** `cli/pyproject.toml:9, 43`
- **Suggested Upstream Fix:** Relax `requires-python` in `cli/pyproject.toml` to `">=3.11"` and `setuptools>=68.0`.
