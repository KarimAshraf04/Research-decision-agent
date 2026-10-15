"""LLM providers + tracing setup.

* `model_for(role)` gives each agent its model. Roles ("smart", "fast") can use different providers, e.g.
  Gemini for the Planner/Writer/Critic and Groq for the specialists - spreading free-tier rate limits.
    - openai           : a plain model name (SDK default client, Responses API)
    - gemini/groq/xai  : OpenAIChatCompletionsModel bound to an AsyncOpenAI client pointed at the provider's
                         OpenAI-compatible endpoint (Chat Completions API).
* `configure()` (call once before running agents) checks the keys and sets up tracing: traces go to the
  OpenAI dashboard when an OpenAI key exists, otherwise LocalTraceProcessor writes them to var/traces/.

LocalTraceProcessor is always installed, so the UI can display the trace of a run whatever the provider.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict

from rdi import config

log = logging.getLogger(__name__)
_configured = False
_lock = threading.Lock()

# group_id (= run id) -> list of finished spans/traces, for the UI
LOCAL_TRACES: dict[str, list[dict]] = defaultdict(list)
_trace_group: dict[str, str] = {}


class LocalTraceProcessor:
    """Implements the SDK's TracingProcessor interface; stores spans in memory and in var/traces/."""

    def on_trace_start(self, trace) -> None:
        data = _export(trace)
        _trace_group[data.get("id", "")] = data.get("group_id") or data.get("id", "")

    def on_trace_end(self, trace) -> None:
        self._write(_export(trace))

    def on_span_start(self, span) -> None:
        pass

    def on_span_end(self, span) -> None:
        self._write(_export(span))

    def shutdown(self) -> None:
        pass

    def force_flush(self) -> None:
        pass

    def _write(self, item: dict) -> None:
        if not item:
            return
        group = _trace_group.get(item.get("trace_id") or item.get("id", ""), "ungrouped")
        LOCAL_TRACES[group].append(item)
        try:
            config.TRACE_DIR.mkdir(parents=True, exist_ok=True)
            with open(config.TRACE_DIR / f"{group}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(item, default=str) + "\n")
        except OSError:
            pass


def _export(obj) -> dict:
    try:
        return obj.export() or {}
    except Exception:
        return {}


def trace_summary(run_id: str) -> list[list]:
    """Rows [started_at, span type, name, duration_ms] for the UI's trace panel."""
    from datetime import datetime

    rows = []
    for item in LOCAL_TRACES.get(run_id, []):
        if item.get("object") != "trace.span":
            continue
        data = item.get("span_data") or {}
        name = data.get("name") or data.get("type", "")
        start, end = item.get("started_at"), item.get("ended_at")
        ms = ""
        try:
            ms = int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000)
        except (TypeError, ValueError):
            pass
        rows.append([str(start)[11:23], data.get("type", ""), name, ms])
    return sorted(rows, key=lambda r: r[0])


_clients: dict = {}


def _client(provider: str):
    if provider not in _clients:
        from openai import AsyncOpenAI

        preset = config.PROVIDER_PRESETS[provider]
        _clients[provider] = AsyncOpenAI(
            base_url=preset["base_url"],
            api_key=config.provider_key(provider) or "missing-key",  # configure() reports missing keys clearly
            max_retries=2,  # short: on repeated 429s the FallbackModel switches model instead of waiting
        )
    return _clients[provider]


# ------------------------------------------------------------------ automatic model fallback
FALLBACK_COOLDOWN_S = {"quota": 600, "rate": 60, "unavailable": 60, "not_found": 3600, "incapable": 3600,
                       "auth": 3600, "other": 30}
_cooling_until: dict[str, float] = {}
_notices: list[str] = []


def classify_failure(e: BaseException) -> str:
    text = f"{type(e).__name__} {e}".lower()
    if "quota" in text or "resource_exhausted" in text:
        return "quota"
    if "429" in text or "ratelimit" in text or "rate limit" in text:
        return "rate"
    if "404" in text or "notfound" in text or "not found" in text:
        return "not_found"
    if "json_validate_failed" in text or "cannot be combined" in text or "not supported" in text:
        return "incapable"
    if "api key" in text or "401" in text or "403" in text or "permission" in text:
        return "auth"
    if any(s in text for s in ("500", "502", "503", "504", "overloaded", "unavailable", "timeout")):
        return "unavailable"
    return "other"


def drain_notices() -> list[str]:
    out = list(_notices)
    _notices.clear()
    return out


async def call_with_fallback(chain: list, call, now=time.monotonic):
    """Try `call(model)` on each (label, model) in order, skipping models that are cooling down.

    On failure the model cools down (10 min for quota, 1 h if it is incapable/not found ...) and the next one
    is tried. If every model is cooling down they are all tried anyway. The last error is re-raised.
    """
    t = now()
    ready = [c for c in chain if _cooling_until.get(c[0], 0) <= t] or list(chain)
    last_error: BaseException | None = None
    for i, (label, model) in enumerate(ready):
        try:
            result = await call(model)
            if i:
                _notices.append(f"answered by fallback model {label}")
            return result
        except Exception as e:  # noqa: BLE001 - provider errors of every kind trigger the fallback
            kind = classify_failure(e)
            _cooling_until[label] = now() + FALLBACK_COOLDOWN_S[kind]
            nxt = ready[i + 1][0] if i + 1 < len(ready) else None
            _notices.append(f"model {label} failed ({kind}: {str(e)[:120]})" +
                            (f" -> switching to {nxt}" if nxt else " -> no fallback left"))
            last_error = e
    raise last_error  # type: ignore[misc]


def _single_model(provider: str, name: str, as_object: bool):
    if provider == "openai":
        if not as_object:
            return name
        from agents import OpenAIProvider

        return OpenAIProvider().get_model(name)
    from agents import OpenAIChatCompletionsModel

    return OpenAIChatCompletionsModel(model=name, openai_client=_client(provider))


def model_for(role: str):
    """Model for an agent role ('smart' or 'fast').

    One model  -> a model name (OpenAI) or a bound OpenAIChatCompletionsModel (other providers).
    Several    -> a FallbackModel that switches to the next model when one fails (quota, 429, 404, ...).
    """
    chain = config.role_chain(role)
    if len(chain) == 1:
        return _single_model(*chain[0], as_object=False)
    from agents import Model

    class FallbackModel(Model):
        def __init__(self, entries):
            self.entries = entries
            self.model = " → ".join(label for label, _ in entries)  # shown in the agent table / UI

        async def get_response(self, *args, **kwargs):
            return await call_with_fallback(self.entries, lambda m: m.get_response(*args, **kwargs))

        def stream_response(self, *args, **kwargs):  # streaming is not used by this project
            return self.entries[0][1].stream_response(*args, **kwargs)

    return FallbackModel([(f"{p}:{n}", _single_model(p, n, as_object=True)) for p, n in chain])


def chain_label(role: str) -> str:
    return " → ".join(n if p == config.ROLE_PROVIDER[role] else f"{p}:{n}" for p, n in config.role_chain(role))


def missing_keys() -> list[str]:
    used = {config.PROVIDER_SMART, config.PROVIDER_FAST}
    return [config.PROVIDER_PRESETS[p]["key_env"] for p in sorted(used) if not config.provider_key(p)]


def configure() -> None:
    global _configured
    with _lock:
        if _configured:
            return
        _configured = True
    try:
        import agents
    except ImportError:
        return
    missing = missing_keys()
    if missing:
        _configured = False
        raise RuntimeError(f"Provider {config.PROVIDER_LABEL} needs {', '.join(missing)} in .env")
    if not hasattr(agents, "add_trace_processor"):  # offline fake SDK
        return

    local = LocalTraceProcessor()
    uses_openai = "openai" in (config.PROVIDER_SMART, config.PROVIDER_FAST)
    if uses_openai or config.OPENAI_API_KEY:
        if config.OPENAI_API_KEY and not uses_openai:
            agents.set_tracing_export_api_key(config.OPENAI_API_KEY)
        agents.add_trace_processor(local)              # OpenAI dashboard + local copy
    else:
        agents.set_trace_processors([local])          # no OpenAI key: local traces only
    log.info("LLM providers=%s smart=%s fast=%s", config.PROVIDER_LABEL, config.MODEL_SMART, config.MODEL_FAST)
