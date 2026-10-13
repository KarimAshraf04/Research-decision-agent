"""Report Writer - the GENERATOR in the evaluator-optimizer loop.

Output: DecisionReport, protected by report_grounding_guardrail (invented citations, flagged-only
claims and echoed injected text are rejected before the Critic ever sees the draft).
"""
from agents import Agent

from rdi import config
from rdi.providers import model_for
from rdi.agent_team.prompts import WRITER
from rdi.agent_team.settings import model_settings
from rdi.context import ResearchContext
from rdi.guardrails import report_grounding_guardrail
from rdi.models import DecisionReport
from rdi.tools import retrieve_evidence

writer_agent = Agent[ResearchContext](
    name="Report Writer",
    model=model_for("smart"),
    model_settings=model_settings(config.MODEL_SMART, 0.3),
    instructions=WRITER,
    tools=[retrieve_evidence],
    output_type=DecisionReport,
    output_guardrails=[report_grounding_guardrail],
)
