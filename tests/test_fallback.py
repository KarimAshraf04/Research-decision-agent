"""Automatic model fallback (providers.call_with_fallback) and chain configuration (config.role_chain)."""
import asyncio

import pytest

from rdi import config, providers


class Boom(Exception):
    pass


def run(chain, now=lambda: 0.0):
    async def call(model):
        return await model()
    return asyncio.run(providers.call_with_fallback(chain, call, now=now))


@pytest.fixture(autouse=True)
def clean_state():
    providers._cooling_until.clear(); providers.drain_notices()
    yield
    providers._cooling_until.clear(); providers.drain_notices()


def ok(value):
    async def m():
        return value
    return m


def fail(msg):
    async def m():
        raise Boom(msg)
    return m


def test_first_model_answers():
    assert run([("a", ok(1)), ("b", ok(2))]) == 1
    assert providers.drain_notices() == []


def test_quota_switches_to_next_and_cools_down():
    assert run([("a", fail("Error code: 429 - You exceeded your current quota")), ("b", ok("B"))]) == "B"
    notes = providers.drain_notices()
    assert any("a failed (quota" in n and "switching to b" in n for n in notes)
    assert providers._cooling_until["a"] == providers.FALLBACK_COOLDOWN_S["quota"]
    # next call skips the cooling model entirely
    assert run([("a", ok("A")), ("b", ok("B"))], now=lambda: 10.0) == "B"


def test_all_cooling_tries_all_anyway_and_raises_last_error():
    with pytest.raises(Boom, match="second"):
        run([("a", fail("503 overloaded first")), ("b", fail("second"))])


@pytest.mark.parametrize("msg,kind", [
    ("Error code: 429 RESOURCE_EXHAUSTED", "quota"), ("429 Too Many Requests", "rate"),
    ("404 model not found", "not_found"), ("json_validate_failed", "incapable"),
    ("json mode cannot be combined with tool calling", "incapable"), ("Please pass a valid API key", "auth"),
    ("503 The model is overloaded", "unavailable"), ("weird", "other"),
])
def test_classify(msg, kind):
    assert providers.classify_failure(Boom(msg)) == kind


def test_gemini_default_chain(monkeypatch):
    monkeypatch.setattr(config, "ROLE_PROVIDER", {"smart": "gemini", "fast": "gemini"})
    monkeypatch.setattr(config, "MODEL_SMART", "gemini-3.8-flash")
    monkeypatch.setattr(config, "MODEL_FAST", "gemini-3.6-flash")
    monkeypatch.delenv("RDI_FALLBACK_MODELS", raising=False)
    smart = config.role_chain("smart")
    assert smart[0] == ("gemini", "gemini-3.8-flash") and len(smart) == 4 and len(set(smart)) == 4
    assert config.role_chain("fast")[0] == ("gemini", "gemini-3.6-flash")
    monkeypatch.setenv("RDI_FALLBACK_MODELS", "none")
    assert config.role_chain("smart") == [("gemini", "gemini-3.8-flash")]
    monkeypatch.setenv("RDI_FALLBACK_MODELS", "gemini-3.5-flash-lite, xai:grok-4")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert config.role_chain("smart") == [("gemini", "gemini-3.8-flash"), ("gemini", "gemini-3.5-flash-lite")]
