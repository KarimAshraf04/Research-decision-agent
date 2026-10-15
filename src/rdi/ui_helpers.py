"""UI helpers: pure functions used by app.py (no Gradio, no LLM -> unit-testable).

Everything the reviewer sees on the approvals tab, and all input validation for the UI, lives here so
that `app.py` stays a thin wiring layer and a bad click can never surface as a stack trace.
"""
from __future__ import annotations

import json

from rdi.models import DecisionReport
from rdi.services.approvals import ApprovalQueue
from rdi.services.evidence import EvidenceStore, validate_report
from rdi.services.publisher import render_markdown

MAX_QUESTION_CHARS = 2000
MAX_CHAT_CHARS = 1500
APPROVAL_HEADERS = ["id", "status", "run", "question", "reasons", "reviewer", "created (UTC)"]
EMPTY_ROW = [["-"] * len(APPROVAL_HEADERS)]


def clean_text(value, limit: int, what: str = "Input") -> str:
    """Strip, drop control chars, and enforce a size limit. Raises ValueError with a user-readable message."""
    text = "" if value is None else str(value)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32).strip()
    if not text:
        raise ValueError(f"{what} is empty.")
    if len(text) > limit:
        raise ValueError(f"{what} is too long ({len(text)} characters, max {limit}).")
    return text


def parse_approval_id(value) -> int:
    """gr.Number gives None / float / '' -> a clean positive int or a friendly error."""
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        raise ValueError("Select a row in the queue (or type a valid approval id) first.") from None
    if n < 1:
        raise ValueError("Approval ids start at 1.")
    return n


def format_reasons(raw) -> str:
    try:
        items = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except (TypeError, ValueError):
        return str(raw)
    return " • ".join(str(i) for i in items)


STATUS_ICON = {"pending": "🟡 pending", "approved": "✅ approved", "rejected": "⛔ rejected"}


def approvals_rows(queue: ApprovalQueue | None = None, status: str | None = "pending") -> list[list]:
    """Rows for the queue table. status=None -> full history (pending + decided)."""
    try:
        rows = (queue or ApprovalQueue()).list(status)
    except Exception as e:  # DB locked / missing -> show a readable row, not a stack trace
        return [["-", f"⚠️ cannot read queue: {type(e).__name__}", "-", "-", "-", "-", "-"]]
    return [[r["id"], STATUS_ICON.get(r["status"], r["status"]), r["run_id"], r["question"][:90],
             format_reasons(r["reasons"]), r["reviewer"] or "-", r["created_at"][:19]] for r in rows] or EMPTY_ROW


def counts_markdown(queue: ApprovalQueue | None = None) -> str:
    try:
        c = (queue or ApprovalQueue()).counts()
    except Exception as e:
        return f"⚠️ Queue unavailable ({type(e).__name__})."
    return f"🟡 **{c['pending']}** pending · ✅ **{c['approved']}** approved · ⛔ **{c['rejected']}** rejected"


def render_approval_report(approval_id: int, queue: ApprovalQueue | None = None) -> str:
    """What the human reviewer must READ before approving: reasons, validator result, the report with sources."""
    queue = queue or ApprovalQueue()
    rec = queue.get(approval_id)
    if rec is None:
        return f"⚠️ No approval #{approval_id}."
    try:
        payload = json.loads(rec["report_json"])
        report = DecisionReport(**payload["report"])
        store = EvidenceStore.from_items(payload["evidence"])
    except Exception as e:
        return f"⚠️ Approval #{approval_id} holds an unreadable report ({type(e).__name__}). Reject it and re-run."
    issues = validate_report(report, store)
    flagged = [e.evidence_id for e in store.items.values() if e.source_flagged]
    head = [f"### Approval #{rec['id']} — {STATUS_ICON.get(rec['status'], rec['status'])}",
            f"**Question:** {rec['question']}",
            f"**Why a human is needed:** {format_reasons(rec['reasons'])}",
            "**Deterministic validator:** " + ("✅ no issues" if not issues else
                                               "⚠️ " + "; ".join(f"`{i.code}` ({i.severity})" for i in issues)),
            "**Sources flagged for prompt injection:** " + (", ".join(flagged) if flagged else "none"),
            "", "---", ""]
    return "\n".join(head) + render_markdown(report, store, None)


def friendly_error(e: BaseException) -> str:
    """One-line message for the UI; the full detail stays in the run timeline / logs."""
    msg = str(e).strip().splitlines()[0] if str(e).strip() else ""
    return f"{type(e).__name__}: {msg[:300]}" if msg else type(e).__name__
