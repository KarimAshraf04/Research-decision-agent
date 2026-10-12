"""Execution helpers shared by every workflow step (owner: Person A).

* `run_agent`  - one Runner.run call with timeline hooks + token-usage accounting.
* `safe_run`   - run_agent with recovery: schema-invalid output, max-turns and API errors are
                 retried with feedback; input-guardrail trips always propagate (the run must stop).
* `step`       - context manager that times a pipeline step and opens a trace span.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager

from agents import (InputGuardrailTripwireTriggered, MaxTurnsExceeded, ModelBehaviorError,
                    OutputGuardrailTripwireTriggered, RunHooks, Runner, custom_span)

from rdi import config
from rdi.context import ResearchContext


class StepFailed(Exception):
    """A pipeline step failed after all retries. The caller decides how to degrade."""


class TimelineHooks(RunHooks):
    """Writes agent start/end events into the run timeline (visible in the UI next to the trace)."""

    async def on_agent_start(self, context, agent, *args, **kwargs) -> None:
        ctx = getattr(context, "context", None)
        if isinstance(ctx, ResearchContext):
            ctx.log("agent", f"start  {agent.name}")

    async def on_agent_end(self, context, agent, output, *args, **kwargs) -> None:
        ctx = getattr(context, "context", None)
        if isinstance(ctx, ResearchContext):
            ctx.log("agent", f"finish {agent.name}")


HOOKS = TimelineHooks()


def record_usage(ctx: ResearchContext, result) -> None:
    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    if usage is None:
        return
    for key in ctx.usage:
        ctx.usage[key] += int(getattr(usage, key, 0) or 0)


async def run_agent(agent, task, ctx: ResearchContext, *, max_turns: int = config.AGENT_MAX_TURNS, session=None):
    result = await Runner.run(agent, task, context=ctx, max_turns=max_turns, hooks=HOOKS, session=session)
    record_usage(ctx, result)
    return result


async def safe_run(agent, task: str, ctx: ResearchContext, *, step: str, retries: int = config.STEP_RETRIES,
                   retry_on_output_guardrail: bool = False, session=None):
    """Run an agent with bounded, feedback-driven retries.

    | failure                              | behaviour                                          |
    |--------------------------------------|----------------------------------------------------|
    | InputGuardrailTripwireTriggered      | re-raised immediately - the request is not allowed |
    | OutputGuardrailTripwireTriggered     | retried with the guardrail findings as feedback    |
    |                                      | (only if retry_on_output_guardrail), else re-raised|
    | ModelBehaviorError (invalid schema)  | retried with the validation error as feedback      |
    | MaxTurnsExceeded                     | retried with a tighter tool budget                 |
    | any other exception (API, timeout)   | retried after exponential backoff                  |
    After `retries` extra attempts -> StepFailed.
    """
    attempt_task, last_error = task, None
    for attempt in range(retries + 1):
        try:
            with custom_span(f"step:{step}", data={"attempt": attempt + 1}):
                return await run_agent(agent, attempt_task, ctx, session=session)
        except InputGuardrailTripwireTriggered:
            raise
        except OutputGuardrailTripwireTriggered as e:
            if not retry_on_output_guardrail or attempt == retries:
                raise
            findings = e.guardrail_result.output.output_info
            ctx.log("recovery", f"{step}: output guardrail rejected attempt {attempt + 1}; retrying with its findings")
            attempt_task = (f"{task}\n\n## YOUR PREVIOUS ANSWER WAS REJECTED BY A GROUNDING CHECK\n{findings}\n"
                            "Fix every item: cite only evidence ids returned by save_evidence.")
            last_error = e
        except ModelBehaviorError as e:
            ctx.log("recovery", f"{step}: invalid structured output ({str(e)[:120]}); retrying")
            attempt_task = (f"{task}\n\n## YOUR PREVIOUS OUTPUT WAS INVALID\n{str(e)[:400]}\n"
                            "Return output that matches the required schema exactly.")
            last_error = e
        except MaxTurnsExceeded as e:
            ctx.log("recovery", f"{step}: max turns exceeded; retrying with a tighter budget")
            attempt_task = f"{task}\n\n## BUDGET\nYou ran out of steps last time. Use at most 6 tool calls, then answer."
            last_error = e
        except Exception as e:  # API errors, rate limits, timeouts
            ctx.log("recovery", f"{step}: {type(e).__name__}: {str(e)[:160]}; backing off")
            await asyncio.sleep(1.5 * (2 ** attempt))
            last_error = e
    raise StepFailed(f"{step} failed after {retries + 1} attempt(s): {type(last_error).__name__}: {last_error}")


@contextmanager
def step(ctx: ResearchContext, name: str, **span_data):
    """Times a pipeline step (stored in ctx.step_seconds) and wraps it in a trace span."""
    t0 = time.time()
    with custom_span(name, data=span_data or None):
        try:
            yield
        finally:
            ctx.step_seconds[name] = round(time.time() - t0, 2)
