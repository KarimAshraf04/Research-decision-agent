"""Research Orchestrator - ORCHESTRATOR-WORKERS (LLM-orchestrated).

The orchestrator LLM decides *which* worker to call, *why* and *with what task*. Python decides
*whether it is allowed*: the delegate_* tools enforce a budget of MAX_DELEGATIONS per run and turn
worker failures into error messages instead of crashing the orchestrator.

Why explicit delegate tools instead of `agent.as_tool()`?
  * the budget and the error handling are enforced in code, not in the prompt,
  * each delegation is logged on the run timeline (visible in the UI and the trace),
  * a worker whose output fails the grounding guardrail returns a clear error the LLM can react to.
"""
from __future__ import annotations

import json

from agents import Agent, OutputGuardrailTripwireTriggered, RunContextWrapper, function_tool

from rdi import config
from rdi.providers import model_for
from rdi.agent_team.prompts import ORCHESTRATOR, UNTRUSTED_DATA_POLICY
from rdi.agent_team.settings import model_settings
from rdi.agent_team.specialists import market_agent, risk_agent, technical_agent
from rdi.context import ResearchContext
from rdi.models import OrchestratorReview
from rdi.runtime import run_agent
from rdi.tools import compare_sources, retrieve_evidence

MAX_DELEGATIONS = 3
MIN_TASK_CHARS = 20


async def _delegate(ctx: RunContextWrapper[ResearchContext], worker: Agent, task: str) -> str:
    c = ctx.context
    task = task.strip()
    if len(task) < MIN_TASK_CHARS:
        return json.dumps({"ok": False, "error": "Task too vague. Say what is missing and which sub-question it serves."})
    if c.delegations_used >= MAX_DELEGATIONS:
        c.log("blocked", f"Delegation to {worker.name} refused: budget of {MAX_DELEGATIONS} used")
        return json.dumps({"ok": False, "error": f"Delegation budget ({MAX_DELEGATIONS}) exhausted. Finish your review."})
    c.delegations_used += 1
    c.log("delegation", f"Orchestrator -> {worker.name} (#{c.delegations_used}): {task[:120]}")
    try:
        result = await run_agent(worker, task, c)
    except OutputGuardrailTripwireTriggered as e:
        c.log("recovery", f"{worker.name} output rejected by grounding guardrail during delegation")
        return json.dumps({"ok": False, "error": "Worker output rejected by the grounding guardrail.",
                           "details": e.guardrail_result.output.output_info})
    except Exception as e:  # max turns, API error, ...
        c.log("recovery", f"Delegation to {worker.name} failed: {type(e).__name__}")
        return json.dumps({"ok": False, "error": f"Worker failed ({type(e).__name__}). Continue without it."})
    return json.dumps({"ok": True, "worker": worker.name, "findings": result.final_output.model_dump()})


@function_tool
async def delegate_technical_research(ctx: RunContextWrapper[ResearchContext], task: str) -> str:
    """Delegate a follow-up task to the Technical Research Specialist (performance, architecture, effort).

    Args:
        task: Precise instructions: what is missing, which sub-question it belongs to, preferred source type.
    """
    return await _delegate(ctx, technical_agent, task)


@function_tool
async def delegate_market_research(ctx: RunContextWrapper[ResearchContext], task: str) -> str:
    """Delegate a follow-up task to the Market Research Specialist (pricing, vendors, adoption).

    Args:
        task: Precise instructions: what is missing, which sub-question it belongs to, preferred source type.
    """
    return await _delegate(ctx, market_agent, task)


@function_tool
async def delegate_risk_research(ctx: RunContextWrapper[ResearchContext], task: str) -> str:
    """Delegate a follow-up task to the Risk & Compliance Specialist (security, compliance, lock-in, outages).

    Args:
        task: Precise instructions: what is missing, which sub-question it belongs to, preferred source type.
    """
    return await _delegate(ctx, risk_agent, task)


orchestrator_agent = Agent[ResearchContext](
    name="Research Orchestrator",
    model=model_for("smart"),
    model_settings=model_settings(config.MODEL_SMART, 0.2),
    instructions=ORCHESTRATOR.format(security=UNTRUSTED_DATA_POLICY),
    tools=[delegate_technical_research, delegate_market_research, delegate_risk_research,
           compare_sources, retrieve_evidence],
    output_type=OrchestratorReview,
)
