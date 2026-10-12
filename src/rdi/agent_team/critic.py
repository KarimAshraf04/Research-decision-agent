"""Critic - the EVALUATOR in the evaluator-optimizer loop.

Output: Critique. Its Pydantic model forces verdict="revise" whenever a major issue is listed, so the
model cannot "approve" a report it has just criticised (rule in code, not in the prompt).
"""
from agents import Agent

from rdi import config
from rdi.agent_team.prompts import CRITIC
from rdi.agent_team.settings import model_settings
from rdi.context import ResearchContext
from rdi.models import Critique
from rdi.tools import check_claim_support, retrieve_evidence

critic_agent = Agent[ResearchContext](
    name="Critic",
    model=config.MODEL_SMART,
    model_settings=model_settings(config.MODEL_SMART, 0.0),
    instructions=CRITIC,
    tools=[check_claim_support, retrieve_evidence],
    output_type=Critique,
)
