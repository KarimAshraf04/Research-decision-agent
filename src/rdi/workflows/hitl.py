"""HUMAN-IN-THE-LOOP gate + reviewer decision.

Two triggers, both decided by Python:
  * before writing : decide_path() marked the run high-impact / sensitive (services/policy.py)
  * after writing  : unresolved major issues or LOW confidence (post_report_escalation)
When triggered, the report goes to the approval queue and is NOT published. Publishing then
requires a named reviewer's approval; publish_report re-checks that approval itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from rdi.context import RUNS, ResearchContext
from rdi.models import DecisionReport, PathDecision
from rdi.services.approvals import ApprovalQueue
from rdi.services.evidence import EvidenceStore
from rdi.services.policy import ActionBlocked, post_report_escalation
from rdi.services.publisher import publish_report


@dataclass
class GateResult:
    status: str
    message: str
    approval_id: int | None = None
    published_path: str | None = None


def apply_gate(ctx: ResearchContext, path: PathDecision, report: DecisionReport, unresolved_major: int) -> GateResult:
    reasons = [r for r in path.reasons if "approval" in r] + post_report_escalation(report, unresolved_major)
    ctx.requires_approval = bool(reasons)

    if reasons:
        payload = json.dumps({"report": report.model_dump(),
                              "evidence": [e.model_dump() for e in ctx.evidence.items.values()]})
        approval_id = ApprovalQueue().create(ctx.run_id, ctx.question, reasons, payload)
        ctx.log("hitl", f"Approval #{approval_id} created", reasons=reasons)
        status = "needs_human_review" if unresolved_major else "pending_approval"
        return GateResult(status, "Stopped for human review: " + " ".join(reasons), approval_id=approval_id)

    try:
        path_out = publish_report(ctx.run_id, report, ctx.evidence, requires_approval=False)
    except ActionBlocked as e:
        ctx.log("blocked", str(e))
        return GateResult("needs_human_review", str(e))
    ctx.published_path = path_out
    ctx.log("action", f"Published {path_out}")
    return GateResult("published", "Report validated and published automatically.", published_path=path_out)


def decide_approval(approval_id: int, approved: bool, reviewer: str, note: str = "") -> str:
    """Called from the Approval tab. Rejection is final; approval triggers the protected publish."""
    queue = ApprovalQueue()
    record = queue.decide(approval_id, approved, reviewer, note)
    if not approved:
        return f"Approval #{approval_id} rejected by {reviewer}. The report will not be published."
    payload = json.loads(record["report_json"])
    report = DecisionReport(**payload["report"])
    ctx = RUNS.get(record["run_id"])
    store = ctx.evidence if ctx else EvidenceStore.from_items(payload["evidence"])  # survives app restarts
    try:
        path_out = publish_report(record["run_id"], report, store, requires_approval=True, queue=queue)
    except ActionBlocked as e:
        return f"Approved, but publishing was blocked: {e}"
    if ctx:
        ctx.published_path = path_out
        ctx.log("action", f"Published after approval #{approval_id} by {reviewer}: {path_out}")
    return f"Approved by {reviewer}. Published to {path_out}"
