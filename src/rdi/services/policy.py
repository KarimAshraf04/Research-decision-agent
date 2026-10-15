"""Deterministic authorisation / safety policy. The LLM can never override these."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from rdi import config
from rdi.models import DecisionReport, PathDecision, ResearchPlan


class ActionBlocked(Exception):
    """Raised when Python policy refuses a tool action. Message is safe to show the LLM/user."""


MAX_URL_LEN = 2048


def _host_as_ip(host: str):
    """Return an IP object if `host` is an IP in ANY notation (dotted, decimal, hex, octal, short), else None.

    `ipaddress` only understands canonical forms, so 'http://2130706433/' or 'http://0x7f000001/' (both =
    127.0.0.1) would slip through a naive check. `inet_aton` accepts those legacy forms like a real resolver.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def check_url_allowed(url: str) -> None:
    """Tool-level guardrail for scrape_page: blocks SSRF, local files, internal hosts, obfuscated IPs."""
    if not isinstance(url, str) or not url.strip():
        raise ActionBlocked("Blocked: URL is empty.")
    url = url.strip()
    if len(url) > MAX_URL_LEN:
        raise ActionBlocked(f"Blocked: URL is longer than {MAX_URL_LEN} characters.")
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise ActionBlocked("Blocked: URL contains whitespace or control characters.")
    try:
        parsed = urlparse(url)
        parsed.port  # noqa: B018 - raises ValueError for an out-of-range / non-numeric port
    except ValueError:
        raise ActionBlocked("Blocked: URL is malformed (bad host or port).") from None
    if parsed.scheme not in config.ALLOWED_SCHEMES:
        raise ActionBlocked(f"Blocked: scheme '{parsed.scheme or 'none'}' is not allowed (only http/https).")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ActionBlocked("Blocked: URL has no host.")
    if host in config.BLOCKED_DOMAINS or host == "localhost" or host.endswith((".internal", ".local", ".localhost")):
        raise ActionBlocked(f"Blocked: '{host}' is an internal/metadata host.")
    ip = _host_as_ip(host)
    if ip is not None:
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global:  # private, loopback, link-local, CGNAT (100.64/10), reserved, multicast...
            raise ActionBlocked(f"Blocked: '{host}' is a private/loopback/non-public address.")
    elif "." not in host:
        raise ActionBlocked(f"Blocked: '{host}' is a single-label (intranet-style) host name.")


def is_sensitive(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in config.SENSITIVE_KEYWORDS)


def decide_path(question: str, plan: ResearchPlan) -> PathDecision:
    """CODE-ORCHESTRATED routing decision (auditable): which path + does a human need to approve."""
    reasons: list[str] = []
    needs_human = False
    if plan.impact_level == "high":
        needs_human = True
        reasons.append("Planner rated business impact HIGH -> human approval required before publishing.")
    if is_sensitive(question):
        needs_human = True
        reasons.append("Question touches a sensitive domain (legal/people/investment/security) -> human approval.")
    quick = len(plan.subquestions) == 1 and plan.impact_level == "low"
    path = "quick" if quick else "full"
    reasons.append(
        "Single low-impact sub-question -> quick path (no orchestrator gap-filling, 2 critic rounds max)."
        if quick else f"{len(plan.subquestions)} sub-questions -> full path (parallel specialists + orchestrator)."
    )
    return PathDecision(path=path, requires_human_approval=needs_human, reasons=reasons)


def post_report_escalation(report: DecisionReport, unresolved_major_issues: int) -> list[str]:
    """Second HITL gate, evaluated after the evaluator loop."""
    reasons = []
    if unresolved_major_issues:
        reasons.append(f"{unresolved_major_issues} major issue(s) unresolved after the max critic iterations.")
    if report.recommendation_confidence == "low":
        reasons.append("Writer's recommendation confidence is LOW.")
    return reasons
