"""Input guardrails: a cheap deterministic layer first, an LLM classifier second.

Both run before the Planner produces anything. If either trips, the SDK raises
InputGuardrailTripwireTriggered and the pipeline returns status="blocked" - no research is done.
"""
from __future__ import annotations

from agents import Agent, GuardrailFunctionOutput, RunContextWrapper, input_guardrail

from rdi.agent_team.scope_classifier import scope_classifier
from rdi.context import ResearchContext
from rdi.models import ScopeCheck
from rdi.runtime import run_agent
from rdi.services.injection import asks_for_secrets, detect_injection

MIN_CHARS, MAX_CHARS = 8, 4000


def latest_user_text(inp) -> str:
    """Guardrails receive either a string or a list of input items (when a session is used)."""
    if isinstance(inp, str):
        return inp
    items = [i for i in (inp or []) if isinstance(i, dict)]
    users = [i for i in items if i.get("role") == "user"] or items
    content = users[-1].get("content", "") if users else ""
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content)


@input_guardrail(name="deterministic_input_guardrail")
async def deterministic_input_guardrail(ctx: RunContextWrapper[ResearchContext], agent: Agent,
                                        inp) -> GuardrailFunctionOutput:
    text = latest_user_text(inp)
    reasons: list[str] = []
    if len(text.strip()) < MIN_CHARS:
        reasons.append("Input too short to be a research question.")
    if len(text) > MAX_CHARS:
        reasons.append(f"Input too long (max {MAX_CHARS} characters).")
    injection = detect_injection(text)
    if injection.is_injection:
        reasons.append(f"Prompt-injection patterns detected: {', '.join(injection.categories)}.")
    if asks_for_secrets(text):
        reasons.append("Request asks for credentials or secrets.")
    if reasons:
        ctx.context.log("guardrail", "Input guardrail (deterministic) tripped: " + " ".join(reasons))
    return GuardrailFunctionOutput(output_info={"guardrail": "deterministic", "reasons": reasons,
                                                "matches": injection.matches},
                                   tripwire_triggered=bool(reasons))


@input_guardrail(name="scope_input_guardrail")
async def scope_input_guardrail(ctx: RunContextWrapper[ResearchContext], agent: Agent,
                                inp) -> GuardrailFunctionOutput:
    result = await run_agent(scope_classifier, latest_user_text(inp), ctx.context, max_turns=2)
    check: ScopeCheck = result.final_output
    tripped = (not check.is_research_question) or check.is_harmful or check.requests_secrets
    if tripped:
        ctx.context.log("guardrail", f"Input guardrail (LLM scope) tripped: {check.reason}")
    return GuardrailFunctionOutput(output_info={"guardrail": "scope", **check.model_dump()},
                                   tripwire_triggered=tripped)
