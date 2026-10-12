"""Output guardrails: an agent's answer is rejected before anyone sees it if it is not grounded.

They reuse the deterministic validators in services/evidence.py, so the same rules are applied by
the guardrail (hard block), by the evaluator loop (feedback) and by publish_report (final gate).
"""
from __future__ import annotations

from agents import Agent, GuardrailFunctionOutput, RunContextWrapper, output_guardrail

from rdi.context import ResearchContext
from rdi.models import DecisionReport, SpecialistFindings, ValidationIssue
from rdi.services.evidence import validate_findings, validate_report
from rdi.services.injection import detect_injection

# Issues serious enough to block a draft outright. Softer issues (e.g. unsupported numbers) are
# left to the evaluator loop, which can fix them through feedback.
BLOCKING_REPORT_CODES = {"invented_citation", "flagged_source_only"}


@output_guardrail(name="findings_grounding_guardrail")
async def findings_grounding_guardrail(ctx: RunContextWrapper[ResearchContext], agent: Agent,
                                       output: SpecialistFindings) -> GuardrailFunctionOutput:
    issues = validate_findings(output, ctx.context.evidence)
    if issues:
        ctx.context.log("guardrail", f"Output guardrail rejected {agent.name}: {len(issues)} ungrounded finding(s)")
    return GuardrailFunctionOutput(output_info=[i.model_dump() for i in issues], tripwire_triggered=bool(issues))


@output_guardrail(name="report_grounding_guardrail")
async def report_grounding_guardrail(ctx: RunContextWrapper[ResearchContext], agent: Agent,
                                     output: DecisionReport) -> GuardrailFunctionOutput:
    issues = [i for i in validate_report(output, ctx.context.evidence) if i.code in BLOCKING_REPORT_CODES]
    body = " ".join([output.executive_summary, output.recommendation, *[f.statement for f in output.key_findings]])
    if detect_injection(body).is_injection:
        issues.append(ValidationIssue(code="echoed_injection",
                                      detail="Report repeats instruction-like text taken from a web page."))
    if issues:
        ctx.context.log("guardrail", f"Output guardrail rejected the report draft: {[i.code for i in issues]}")
    return GuardrailFunctionOutput(output_info=[i.model_dump() for i in issues], tripwire_triggered=bool(issues))
