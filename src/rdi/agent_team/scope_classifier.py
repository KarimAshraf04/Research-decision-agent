"""LLM classifier used by scope_input_guardrail. Cheap model, temperature 0."""
from agents import Agent

from rdi import config
from rdi.agent_team.prompts import SCOPE_CLASSIFIER
from rdi.agent_team.settings import model_settings
from rdi.models import ScopeCheck

scope_classifier = Agent(
    name="Scope Guardrail Classifier",
    model=config.MODEL_FAST,
    model_settings=model_settings(config.MODEL_FAST, 0.0),
    instructions=SCOPE_CLASSIFIER,
    output_type=ScopeCheck,
)
