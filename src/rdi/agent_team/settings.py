"""Model settings per role. Reasoning models (o-series, gpt-5) reject `temperature`, so it is
only set for models that accept it - switching models in .env needs no code change."""
from __future__ import annotations

from datetime import date

from agents import ModelSettings

from rdi.agent_team.prompts import PROMPT_VERSION

_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def model_settings(model: str, temperature: float) -> ModelSettings:
    if model.startswith(_REASONING_PREFIXES):
        return ModelSettings()
    return ModelSettings(temperature=temperature)


def today() -> str:
    return date.today().isoformat()


TRACE_METADATA = {"prompt_version": PROMPT_VERSION}
