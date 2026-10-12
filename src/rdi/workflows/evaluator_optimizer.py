"""EVALUATOR-OPTIMIZER - Report Writer (generator) <-> Critic (evaluator).

Each iteration:
  1. Writer drafts (output guardrail may reject the draft outright -> feedback, next iteration)
  2. Deterministic validator checks citations/numbers (services/evidence.py)
  3. Critic scores the draft and lists issues
Stop conditions (all in code):
  * APPROVED   : no deterministic major issue AND critic verdict "approve" AND score >= pass score
  * MAX_ITER   : iteration budget used (3 on the full path, 2 on the quick path)
  * STAGNATION : the same major issues appear twice in a row - more rounds will not help
The best draft (fewest major issues, then highest score) is returned, not merely the last one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from agents import OutputGuardrailTripwireTriggered

from rdi import config
from rdi.agent_team.critic import critic_agent
from rdi.agent_team.writer import writer_agent
from rdi.context import ResearchContext
from rdi.models import (Critique, DecisionReport, IterationRecord, OrchestratorReview, ResearchPlan,
                        SpecialistFindings, ValidationIssue)
from rdi.runtime import StepFailed, safe_run
from rdi.services.evidence import validate_report

# Clearly labelled demo fault injection, applied ONLY to draft 1 when selected in the UI.
DEMO_DRAFT_FAULTS = {
    "invented_citation": ("[DEMO FAULT INJECTION] In this draft add the key finding "
                          "'The change cuts costs by 75 percent' citing E99."),
    "unsupported_claim": ("[DEMO FAULT INJECTION] In this draft add a key finding claiming a 75 percent "
                          "improvement, citing E1, and set recommendation_confidence to high."),
}


@dataclass
class EvaluationOutcome:
    report: DecisionReport | None
    iterations: list[IterationRecord] = field(default_factory=list)
    unresolved_major: int = 0
    stop_reason: str = ""


def build_research_package(plan: ResearchPlan, findings: list[SpecialistFindings],
                           review: OrchestratorReview | None, ctx: ResearchContext) -> str:
    return "\n\n".join([
        "## RESEARCH PLAN\n" + plan.model_dump_json(indent=1),
        "## SPECIALIST FINDINGS\n" + json.dumps([f.model_dump() for f in findings], indent=1),
        "## ORCHESTRATOR REVIEW\n" + (review.model_dump_json(indent=1) if review else "(not run on this path)"),
        "## EVIDENCE TABLE (the ONLY citable ids)\n" + ctx.evidence.as_table(),
    ])


def _feedback(det: list[ValidationIssue], critique: Critique | None) -> str:
    lines = [f"- [validator:{d.severity}] {d.code}: {d.detail}" for d in det]
    if critique:
        lines += [f"- [critic:{i.severity}] {i.issue_type} @ {i.location}: {i.detail}" for i in critique.issues]
        lines.append(f"Critic instructions: {critique.revision_instructions}")
    return "\n".join(lines)


def _major_signature(det: list[ValidationIssue], critique: Critique | None) -> frozenset[str]:
    keys = {f"v:{d.code}:{d.detail}" for d in det if d.severity == "major"}
    if critique:
        keys |= {f"c:{i.issue_type}:{i.location}" for i in critique.issues if i.severity == "major"}
    return frozenset(keys)


async def write_and_refine(package: str, ctx: ResearchContext, max_iterations: int) -> EvaluationOutcome:
    outcome = EvaluationOutcome(report=None)
    best_rank: tuple[int, int] | None = None
    feedback, previous_signature = "", None

    for i in range(1, max_iterations + 1):
        record = IterationRecord(iteration=i)
        outcome.iterations.append(record)
        task = package + (f"\n\n## CRITIC FEEDBACK TO FIX\n{feedback}" if feedback else "")
        if i == 1 and ctx.draft_fault in DEMO_DRAFT_FAULTS:
            task += "\n\n" + DEMO_DRAFT_FAULTS[ctx.draft_fault]
            ctx.log("fault", f"Demo fault injected into draft 1: {ctx.draft_fault}")

        # 1. generate
        try:
            draft: DecisionReport = (await safe_run(writer_agent, task, ctx, step=f"write#{i}")).final_output
        except OutputGuardrailTripwireTriggered as e:
            info = e.guardrail_result.output.output_info
            record.guardrail_blocked = json.dumps(info)
            feedback = (f"The previous draft was REJECTED by the output guardrail: {info}. "
                        "Cite only evidence ids that appear in the evidence table.")
            ctx.log("evaluator", f"iteration {i}: draft blocked by output guardrail")
            continue
        except StepFailed as e:
            ctx.log("recovery", f"write#{i} failed: {e}")
            continue

        # 2. deterministic validation
        det = validate_report(draft, ctx.evidence)
        record.deterministic_issues = det

        # 3. evaluate
        critique: Critique | None = None
        try:
            critic_task = (f"## REPORT\n{draft.model_dump_json(indent=1)}\n\n"
                           f"## DETERMINISTIC VALIDATOR ISSUES\n{[d.model_dump() for d in det] or 'none'}\n\n"
                           f"## EVIDENCE TABLE\n{ctx.evidence.as_table()}")
            critique = (await safe_run(critic_agent, critic_task, ctx, step=f"critique#{i}")).final_output
        except StepFailed as e:
            ctx.log("recovery", f"Critic failed ({e}); relying on deterministic validation only")
        record.critique = critique

        det_major = sum(d.severity == "major" for d in det)
        critic_major = sum(x.severity == "major" for x in critique.issues) if critique else 0
        majors, score = det_major + critic_major, (critique.score if critique else 0)
        ctx.log("evaluator", f"iteration {i}: score={critique.score if critique else 'n/a'} "
                             f"verdict={critique.verdict if critique else 'n/a'} major_issues={majors}")

        rank = (majors, -score)
        if best_rank is None or rank < best_rank:
            best_rank, outcome.report, outcome.unresolved_major = rank, draft, majors

        approved = det_major == 0 and (critique is None or
                                       (critique.verdict == "approve" and critique.score >= config.CRITIC_PASS_SCORE))
        if approved:
            outcome.report, outcome.unresolved_major, outcome.stop_reason = draft, 0, f"approved at iteration {i}"
            break

        signature = _major_signature(det, critique)
        if signature and signature == previous_signature:
            outcome.stop_reason = f"stagnation: same major issues in iterations {i - 1} and {i}"
            break
        previous_signature, feedback = signature, _feedback(det, critique)
    else:
        outcome.stop_reason = f"max iterations ({max_iterations}) reached"

    if outcome.report is None:
        outcome.stop_reason = "no acceptable draft produced"
    ctx.log("evaluator", f"Stopped: {outcome.stop_reason}")
    return outcome
