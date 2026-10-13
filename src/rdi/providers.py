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
            max_retries=6,  # the client backs off automatically on HTTP 429 (free-tier rate limits)
        )
    return _clients[provider]


def model_for(role: str):
    """Model for an agent role ('smart' or 'fast'): a name for OpenAI, a bound model object otherwise."""
    provider = config.ROLE_PROVIDER[role]
    name = config.MODEL_SMART if role == "smart" else config.MODEL_FAST
    if provider == "openai":
        return name
    from agents import OpenAIChatCompletionsModel

    return OpenAIChatCompletionsModel(model=name, openai_client=_client(provider))


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
