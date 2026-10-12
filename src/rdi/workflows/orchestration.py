"""ORCHESTRATOR-WORKERS step. Only runs on the 'full' path (decided by code in services/policy.py).

If the orchestrator fails, the pipeline degrades gracefully: the report is written from the parallel
findings alone, and the timeline records why.
"""
from __future__ import annotations

import json

from agents import OutputGuardrailTripwireTriggered

from rdi.agent_team.orchestrator import orchestrator_agent
from rdi.context import ResearchContext
from rdi.models import OrchestratorReview, ResearchPlan, SpecialistFindings
from rdi.runtime import StepFailed, safe_run


def build_orchestrator_task(plan: ResearchPlan, findings: list[SpecialistFindings], ctx: ResearchContext) -> str:
    gaps = [f"{f.subquestion_id}: {g}" for f in findings for g in f.gaps]
    return (f"Decision question: {plan.restated_question}\n\n"
            f"## SUB-QUESTIONS\n" + "\n".join(f"- {s.id} [{s.track}] {s.question}" for s in plan.subquestions) +
            f"\n\n## SPECIALIST FINDINGS\n{json.dumps([f.model_dump() for f in findings], indent=1)}\n\n"
            f"## KNOWN GAPS\n" + ("\n".join(f"- {g}" for g in gaps) or "none reported") +
            f"\n\n## EVIDENCE TABLE\n{ctx.evidence.as_table()}")


async def run_orchestrator(plan: ResearchPlan, findings: list[SpecialistFindings],
                           ctx: ResearchContext) -> OrchestratorReview | None:
    try:
        result = await safe_run(orchestrator_agent, build_orchestrator_task(plan, findings, ctx), ctx,
                                step="orchestrator")
    except (StepFailed, OutputGuardrailTripwireTriggered) as e:
        ctx.log("recovery", f"Orchestrator skipped ({type(e).__name__}); writing from parallel findings only")
        return None
    review: OrchestratorReview = result.final_output
    ctx.log("orchestrator", f"{ctx.delegations_used} delegation(s), {len(review.conflicts)} conflict(s) recorded")
    return review
