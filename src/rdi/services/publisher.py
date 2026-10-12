"""PROTECTED ACTION: publishing the final report.

Python decides whether publishing is allowed - the agent can ask, but cannot bypass:
  1. the report must pass deterministic citation validation (no major issues), and
  2. if the run requires human approval, an APPROVED record must exist for that run.
"""
from __future__ import annotations

from rdi import config
from rdi.models import DecisionReport
from rdi.services.approvals import ApprovalQueue
from rdi.services.evidence import EvidenceStore, validate_report
from rdi.services.policy import ActionBlocked


def render_markdown(report: DecisionReport, store: EvidenceStore, approval: dict | None) -> str:
    md = [f"# {report.title}", "", f"**Question:** {report.question}", ""]
    if approval:
        md += [f"> Approved by **{approval['reviewer']}** (approval #{approval['id']}). {approval.get('note') or ''}", ""]
    md += ["## Executive summary", report.executive_summary, "",
           f"## Recommendation  _(confidence: {report.recommendation_confidence})_", report.recommendation, "",
           "## Options"]
    for o in report.options:
        md.append(f"### {o.option}  {' '.join('['+e+']' for e in o.evidence_ids)}")
        md += [f"- ✅ {p}" for p in o.pros] + [f"- ⚠️ {c}" for c in o.cons] + [""]
    md.append("## Key findings")
    md += [f"- {f.statement} {' '.join('['+e+']' for e in f.evidence_ids)} _(confidence: {f.confidence})_" for f in report.key_findings]
    md += ["", "## Risks"] + [f"- {r}" for r in report.risks]
    md += ["", "## Open questions"] + [f"- {q}" for q in report.open_questions]
    md += ["", "## Sources"]
    for eid in report.citations:
        e = store.get(eid)
        if e:
            md.append(f"- **[{eid}]** {e.publisher} — *{e.source_title}* ({e.url}), quality {e.source_quality}: \"{e.quote}\"")
    return "\n".join(md) + "\n"


def publish_report(run_id: str, report: DecisionReport, store: EvidenceStore, requires_approval: bool,
                   queue: ApprovalQueue | None = None) -> str:
    major = [i for i in validate_report(report, store) if i.severity == "major"]
    if major:
        raise ActionBlocked("Publishing blocked: report failed citation validation: " + "; ".join(i.detail for i in major))
    approval = None
    if requires_approval:
        approval = (queue or ApprovalQueue()).latest_for_run(run_id)
        if not approval or approval["status"] != "approved":
            state = approval["status"] if approval else "missing"
            raise ActionBlocked(f"Publishing blocked: this run requires human approval (current status: {state}).")
    path = config.OUTPUT_DIR / f"report_{run_id}.md"
    path.write_text(render_markdown(report, store, approval), encoding="utf-8")
    return str(path)
