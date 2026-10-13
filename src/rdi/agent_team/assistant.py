"""Research Assistant - follow-up chat with conversation memory (SQLiteSession).

It may *request* the protected publish_report action; Python (services/publisher.py) decides
whether that is allowed (citations valid + human approval when required).
"""
from agents import Agent

from rdi import config
from rdi.providers import model_for
from rdi.agent_team.prompts import ASSISTANT, UNTRUSTED_DATA_POLICY
from rdi.agent_team.settings import model_settings
from rdi.context import ResearchContext
from rdi.guardrails import deterministic_input_guardrail
from rdi.tools import publish_report, retrieve_evidence, scrape_page

assistant_agent = Agent[ResearchContext](
    name="Research Assistant",
    model=model_for("fast"),
    model_settings=model_settings(config.MODEL_FAST, 0.3),
    instructions=ASSISTANT.format(security=UNTRUSTED_DATA_POLICY),
    tools=[retrieve_evidence, scrape_page, publish_report],
    input_guardrails=[deterministic_input_guardrail],
)
