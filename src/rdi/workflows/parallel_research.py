"""PARALLELIZATION - independent sub-questions are researched concurrently.

Python fans out one specialist run per route with asyncio.gather (bounded by a semaphore), then
fans in. A failed branch never sinks the run: `return_exceptions=True` keeps the other branches,
and the failure is logged for the timeline.
"""
from __future__ import annotations

import asyncio

from rdi import config
from rdi.agent_team.specialists import SPECIALISTS
from rdi.context import ResearchContext
from rdi.models import ResearchPlan, RouteDecision, SpecialistFindings
from rdi.runtime import safe_run


def build_specialist_task(plan: ResearchPlan, route: RouteDecision) -> str:
    sq = next((s for s in plan.subquestions if s.id == route.subquestion_id), None)
    if sq is not None:
        return (f"Main decision question: {plan.restated_question}\n"
                f"Sub-question {sq.id}: {sq.question}\n"
                f"Suggested search queries: {sq.search_queries}\n"
                f"Return subquestion_id='{sq.id}' and track='{sq.track}'.")
    # Route added by the code rule "every multi-part decision gets a risk review"
    return (f"Main decision question: {plan.restated_question}\n"
            "Identify the main risks of this decision: security, outages, compliance, vendor lock-in and "
            f"hidden costs.\nReturn subquestion_id='{route.subquestion_id}' and track='risk'.")


async def run_specialists_in_parallel(plan: ResearchPlan, routes: list[RouteDecision],
                                      ctx: ResearchContext) -> list[SpecialistFindings]:
    semaphore = asyncio.Semaphore(config.MAX_PARALLEL)

    async def research(route: RouteDecision) -> SpecialistFindings:
        async with semaphore:
            ctx.log("parallel", f"start  {route.subquestion_id} -> {route.specialist}")
            result = await safe_run(SPECIALISTS[route.specialist], build_specialist_task(plan, route), ctx,
                                    step=f"research:{route.subquestion_id}", retry_on_output_guardrail=True)
            findings: SpecialistFindings = result.final_output
            ctx.log("parallel", f"finish {route.subquestion_id}: {len(findings.findings)} finding(s)")
            return findings

    outcomes = await asyncio.gather(*(research(r) for r in routes), return_exceptions=True)

    collected: list[SpecialistFindings] = []
    for route, outcome in zip(routes, outcomes):
        if isinstance(outcome, BaseException):
            ctx.log("recovery", f"{route.subquestion_id} failed ({type(outcome).__name__}); continuing without it")
        else:
            collected.append(outcome)
    return collected
