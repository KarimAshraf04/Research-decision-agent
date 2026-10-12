"""Deterministic authorisation / safety policy. The LLM can never override these."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from rdi import config
from rdi.models import DecisionReport, PathDecision, ResearchPlan


class ActionBlocked(Exception):
    """Raised when Python policy refuses a tool action. Message is safe to show the LLM/user."""


def check_url_allowed(url: str) -> None:
    """Tool-level guardrail for scrape_page: blocks SSRF, local files, internal hosts."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in config.ALLOWED_SCHEMES:
        raise ActionBlocked(f"Blocked: scheme '{parsed.scheme or 'none'}' is not allowed (only http/https).")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ActionBlocked("Blocked: URL has no host.")
    if host in config.BLOCKED_DOMAINS or host.endswith(".internal") or host.endswith(".local"):
        raise ActionBlocked(f"Blocked: '{host}' is an internal/metadata host.")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ActionBlocked(f"Blocked: '{host}' is a private/loopback address.")
    except ValueError:
        pass  # not an IP literal - fine


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
