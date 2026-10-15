"""Specialist research workers (Technical, Market, Risk).

Same tools and protocol, different focus. Each returns SpecialistFindings and is protected by
findings_grounding_guardrail (every cited evidence id must exist in this run's evidence store).
They are used twice: in parallel by code (step 3) and on demand by the Orchestrator (step 4).
"""
from agents import Agent

from rdi import config
from rdi.providers import model_for
from rdi.agent_team.prompts import SPECIALIST, SPECIALIST_FOCUS, UNTRUSTED_DATA_POLICY
from rdi.agent_team.settings import model_settings
from rdi.context import ResearchContext
from rdi.guardrails import findings_grounding_guardrail
from rdi.models import SpecialistFindings
from rdi.tools import RESEARCH_TOOLS


def _make_specialist(name: str) -> Agent[ResearchContext]:
    return Agent[ResearchContext](
        name=name,
        model=model_for("fast"),
        model_settings=model_settings(config.MODEL_FAST, 0.1),
        instructions=SPECIALIST.format(name=name, focus=SPECIALIST_FOCUS[name], security=UNTRUSTED_DATA_POLICY),
        tools=RESEARCH_TOOLS,
        output_type=SpecialistFindings,
        output_guardrails=[findings_grounding_guardrail],
    )


technical_agent = _make_specialist("Technical Research Specialist")
market_agent = _make_specialist("Market Research Specialist")
risk_agent = _make_specialist("Risk & Compliance Specialist")

# Name -> agent. Names must match SPECIALIST_BY_TRACK in workflows/routing.py.
SPECIALISTS: dict[str, Agent[ResearchContext]] = {a.name: a for a in (technical_agent, market_agent, risk_agent)}
