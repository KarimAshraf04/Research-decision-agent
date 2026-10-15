"""Follow-up chat with conversation memory.

SQLiteSession keeps the conversation per browser session (session_id), so "what about the risks?"
works after "summarise the report". The run context gives the assistant the run's evidence.

The assistant only answers questions about the loaded run. Python enforces this:
  * no run loaded            -> fixed reply, the model is not called;
  * in_scope = false         -> fixed refusal;
  * cites unknown evidence   -> fixed "cannot confirm" reply (no invented citations reach the user).
"""
from __future__ import annotations

import re

from agents import InputGuardrailTripwireTriggered, SQLiteSession, trace

from rdi import config, providers
from rdi.agent_team.assistant import assistant_agent
from rdi.agent_team.settings import TRACE_METADATA
from rdi.context import RUNS
from rdi.models import ChatReply
from rdi.runtime import StepFailed, safe_run

NO_RUN_REPLY = "No research run is loaded. Run a research question first, then ask about its report."
OFF_TOPIC_REPLY = "I only answer questions about the loaded research run (its report, evidence, sources and approval)."
UNVERIFIED_REPLY = "I can't confirm that from the saved evidence for this run."
_EVIDENCE_ID = re.compile(r"\bE\d+\b")


def finalize_reply(output, known_ids: set[str]) -> str:
    """Turn the assistant's output into the exact text shown to the user."""
    if not isinstance(output, ChatReply):          # plain text (e.g. a tool result echoed back)
        return str(output).strip()
    if not output.in_scope:
        return OFF_TOPIC_REPLY
    answer = output.answer.strip()
    cited = set(output.evidence_ids) | set(_EVIDENCE_ID.findall(answer))
    if not answer or cited - known_ids:
        return UNVERIFIED_REPLY
    return answer


async def chat(message: str, session_id: str, run_id: str | None) -> str:
    ctx = RUNS.get(run_id or "")
    if ctx is None:
        return NO_RUN_REPLY
    providers.configure()
    session = SQLiteSession(session_id, config.SESSION_DB)
    with trace("Research follow-up chat", group_id=session_id, metadata={"run_id": ctx.run_id, **TRACE_METADATA}):
        try:
            result = await safe_run(assistant_agent, message, ctx, step="chat", session=session)
        except InputGuardrailTripwireTriggered as e:
            return f"Blocked by input guardrail: {e.guardrail_result.output.output_info}"
        except StepFailed as e:
            return f"The assistant could not respond ({e}). Please try again."
    return finalize_reply(result.final_output, set(ctx.evidence.items))
