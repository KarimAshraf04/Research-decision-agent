"""Follow-up chat with conversation memory.

SQLiteSession keeps the conversation per browser session (session_id), so "what about the risks?"
works after "summarise the report". The run context gives the assistant the run's evidence.
"""
from __future__ import annotations

from agents import InputGuardrailTripwireTriggered, SQLiteSession, trace

from rdi import config, providers
from rdi.agent_team.assistant import assistant_agent
from rdi.agent_team.settings import TRACE_METADATA
from rdi.context import RUNS, ResearchContext
from rdi.runtime import StepFailed, safe_run


async def chat(message: str, session_id: str, run_id: str | None) -> str:
    providers.configure()
    ctx = RUNS.get(run_id or "")
    if ctx is None:
        ctx = ResearchContext()
        message = f"(No research run is loaded yet.) {message}"
    session = SQLiteSession(session_id, config.SESSION_DB)
    with trace("Research follow-up chat", group_id=session_id, metadata={"run_id": ctx.run_id, **TRACE_METADATA}):
        try:
            result = await safe_run(assistant_agent, message, ctx, step="chat", session=session)
        except InputGuardrailTripwireTriggered as e:
            return f"Blocked by input guardrail: {e.guardrail_result.output.output_info}"
        except StepFailed as e:
            return f"The assistant could not respond ({e}). Please try again."
    return str(result.final_output)
