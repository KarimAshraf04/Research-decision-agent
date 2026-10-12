"""Deterministic prompt-injection detection.

Used in three places:
  1. input guardrail (user messages)
  2. scrape_page tool (web content is UNTRUSTED -> sanitised before the LLM sees it)
  3. output guardrail (report must not echo injected instructions)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERNS: list[tuple[str, str]] = [
    ("override", r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|all|earlier|system)\b.{0,20}\b(instructions?|prompts?|rules?|directions?)"),
    ("role_hijack", r"\byou are now\b|\bact as (an? )?(unrestricted|jailbroken|developer mode)|\bDAN\b"),
    ("system_spoof", r"(system note to ai|note to (ai|llm|assistant)s?|<\s*/?\s*system\s*>|\[system\]|###\s*system)"),
    ("prompt_leak", r"\b(reveal|print|show|repeat|output)\b.{0,25}\b(system prompt|hidden instructions|your instructions|developer message)"),
    ("exfiltration", r"\b(send|post|upload|forward)\b.{0,40}\b(https?://|api key|credentials|password|token)"),
    ("source_rating", r"\brate this source as\b|\bthis is the most reliable source\b"),
    ("suppression", r"\bdo not (mention|cite|include|report)\b.{0,40}\b(risks?|sources?|fees|lock-?in|costs?)"),
]
_COMPILED = [(name, re.compile(rx, re.IGNORECASE | re.DOTALL)) for name, rx in _PATTERNS]

_SECRETS = re.compile(
    r"\b(api[_ -]?key|password|passwd|secret key|access token|bearer token|private key|credentials?)\b",
    re.IGNORECASE,
)


@dataclass
class InjectionResult:
    is_injection: bool
    categories: list[str] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)


def detect_injection(text: str) -> InjectionResult:
    cats, matches = [], []
    for name, rx in _COMPILED:
        for m in rx.finditer(text or ""):
            cats.append(name)
            matches.append(m.group(0)[:120])
    cats = list(dict.fromkeys(cats))
    return InjectionResult(is_injection=bool(cats), categories=cats, matches=matches)


def asks_for_secrets(text: str) -> bool:
    """User asks the system to reveal / handle credentials."""
    return bool(_SECRETS.search(text or "")) and bool(
        re.search(r"\b(give|show|reveal|tell|print|list|find|get|what is|share)\b", text or "", re.IGNORECASE)
    )


def sanitize_untrusted(text: str) -> tuple[str, InjectionResult]:
    """Redact injected instructions from untrusted content (web pages, tool output).

    The sentence containing the injection is replaced, so the LLM never receives it,
    and the result is returned so callers can flag / down-rank the source.
    """
    result = detect_injection(text)
    if not result.is_injection:
        return text, result
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for s in sentences:
        if detect_injection(s).is_injection:
            kept.append("[REDACTED: instruction-like text removed by injection filter]")
        else:
            kept.append(s)
    return " ".join(kept), result
