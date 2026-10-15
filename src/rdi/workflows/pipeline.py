"""The research pipeline - top level. Read this file first: every pattern is one call.

    question
       │   input guardrails (deterministic + LLM)              guardrails/input_guardrails.py
       ▼
    1  Planner -> ResearchPlan                                  PROMPT CHAINING        agent_team/planner.py
    2  decide_path + route_subquestions (Python)                ROUTING (code)         workflows/routing.py
    3  specialists via asyncio.gather                           PARALLELIZATION        workflows/parallel_research.py
    4  Orchestrator delegates follow-up work                    ORCHESTRATOR-WORKERS   workflows/orchestration.py
    5  Writer <-> Critic until approved / max / stagnation      EVALUATOR-OPTIMIZER    workflows/evaluator_optimizer.py
    6  HITL gate -> approval queue or protected publish         HUMAN-IN-THE-LOOP      workflows/hitl.py
"""
from __future__ import annotations

from agents import InputGuardrailTripwireTriggered, trace

from rdi import config, providers
from rdi.agent_team.planner import planner_agent
from rdi.agent_team.settings import TRACE_METADATA
from rdi.context import RUNS, ResearchContext
from rdi.models import PipelineResult, ResearchPlan
from rdi.runtime import StepFailed, safe_run, step
from rdi.services.policy import decide_path
from rdi.workflows.evaluator_optimizer import build_research_package, write_and_refine
from rdi.workflows.hitl import apply_gate, decide_approval  # noqa: F401  (decide_approval re-exported for app.py)
from rdi.workflows.orchestration import run_orchestrator
from rdi.workflows.parallel_research import run_specialists_in_parallel
from rdi.workflows.routing import route_subquestions


async def run_research(question: str, *, search_outage: bool = False, draft_fault: str = "none") -> PipelineResult:
    providers.configure()
    ctx = ResearchContext(question=question.strip(), fault_search_outage=search_outage, draft_fault=draft_fault)
    RUNS[ctx.run_id] = ctx
    result = PipelineResult(run_id=ctx.run_id, status="failed", message="")

    with trace("Research & Decision Pipeline", group_id=ctx.run_id,
               metadata={"run_id": ctx.run_id, **TRACE_METADATA}):
        try:
            await _run_steps(ctx, result)
        except StepFailed as e:  # a step without a graceful fallback failed
            result.status, result.message = "failed", str(e)
            ctx.log("error", str(e))

    result.events, result.metrics = ctx.events, ctx.metrics()
    return result


async def _run_steps(ctx: ResearchContext, result: PipelineResult) -> None:
    # 1 ─ PROMPT CHAINING: plan (input guardrails run here) ──────────────────────────────────────
    with step(ctx, "1_plan"):
        try:
            plan: ResearchPlan = (await safe_run(planner_agent, ctx.question, ctx, step="plan")).final_output
        except InputGuardrailTripwireTriggered as e:
            result.status = "blocked"
            result.message = f"Request blocked by input guardrail: {e.guardrail_result.output.output_info}"
            return
    result.plan = plan
    ctx.log("chain", f"Plan ready: {len(plan.subquestions)} sub-question(s), impact={plan.impact_level}")

    # 2 ─ ROUTING (code-orchestrated) ──────────────────────────────────────────────────────────────
    with step(ctx, "2_route"):
        result.path = path = decide_path(ctx.question, plan)
        result.routes = routes = route_subquestions(plan)
    for reason in path.reasons:
        ctx.log("route", reason)

    # 3 ─ PARALLELIZATION ─────────────────────────────────────────────────────────────────────────
    with step(ctx, "3_parallel_research", branches=len(routes)):
        result.findings = findings = await run_specialists_in_parallel(plan, routes, ctx)
    if not findings:
        reasons = [e["message"] for e in ctx.events if e["kind"] == "recovery" and " failed: " in e["message"]]
        result.message = ("All specialists failed; no evidence was collected. Please retry later."
                          + (f"\n\nFirst error: {reasons[0]}" if reasons else ""))
        return

    # 4 ─ ORCHESTRATOR-WORKERS (full path only) ──────────────────────────────────────────────────
    review = None
    if path.path == "full":
        with step(ctx, "4_orchestrator"):
            review = await run_orchestrator(plan, findings, ctx)
    result.orchestrator_review = review

    # 5 ─ EVALUATOR-OPTIMIZER ─────────────────────────────────────────────────────────────────────
    max_iterations = config.MAX_CRITIC_ITERATIONS if path.path == "full" else 2
    with step(ctx, "5_write_and_critique"):
        outcome = await write_and_refine(build_research_package(plan, findings, review, ctx), ctx, max_iterations)
    result.iterations, result.removed_findings = outcome.iterations, outcome.removed_findings
    if outcome.report is None:
        result.status = "needs_human_review"
        result.message = "No draft passed the output guardrail; escalated to a human analyst."
        return
    result.report = ctx.report = outcome.report

    # 6 ─ HUMAN-IN-THE-LOOP gate ──────────────────────────────────────────────────────────────────
    with step(ctx, "6_hitl_gate"):
        gate = apply_gate(ctx, path, outcome.report, outcome.unresolved_major)
    result.status, result.message = gate.status, f"{gate.message} (evaluator: {outcome.stop_reason})"
    result.approval_id, result.published_path = gate.approval_id, gate.published_path
