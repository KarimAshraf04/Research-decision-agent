"""Research Planner - PROMPT CHAINING step 1.

Input : the raw user question (both input guardrails run here, before any research starts).
Output: ResearchPlan (Pydantic) - the structured intermediate output every later step consumes.
"""
from agents import Agent

from rdi import config
from rdi.providers import model_for
from rdi.agent_team.prompts import PLANNER
from rdi.agent_team.settings import model_settings, today
from rdi.context import ResearchContext
from rdi.guardrails import deterministic_input_guardrail, scope_input_guardrail
from rdi.models import ResearchPlan


def _instructions(ctx, agent) -> str:
    return PLANNER.replace("{today}", today())


planner_agent = Agent[ResearchContext](
    name="Research Planner",
    model=model_for("smart"),
    model_settings=model_settings(config.MODEL_SMART, 0.2),
    instructions=_instructions,
    output_type=ResearchPlan,
    input_guardrails=[deterministic_input_guardrail, scope_input_guardrail],
)
