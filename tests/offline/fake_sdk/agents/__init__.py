"""FAKE openai-agents package for offline tests - NOT the real SDK.

Implements only the API surface this project uses, with the same semantics that matter for the
workflow logic: input guardrails run before the agent, output guardrails after it, tripwires raise
the same exception types, Runner.run returns an object with .final_output and .context_wrapper.usage.
Agent behaviour is scripted per agent name via SCRIPT (see tests/offline/scenarios.py).
"""
from __future__ import annotations

import contextlib


class AgentsException(Exception):
    pass


class ModelBehaviorError(AgentsException):
    pass


class MaxTurnsExceeded(AgentsException):
    pass


class _GuardrailResult:
    def __init__(self, output):
        self.output = output


class InputGuardrailTripwireTriggered(AgentsException):
    def __init__(self, output):
        self.guardrail_result = _GuardrailResult(output)
        super().__init__(str(output.output_info))


class OutputGuardrailTripwireTriggered(AgentsException):
    def __init__(self, output):
        self.guardrail_result = _GuardrailResult(output)
        super().__init__(str(output.output_info))


class GuardrailFunctionOutput:
    def __init__(self, output_info=None, tripwire_triggered=False):
        self.output_info, self.tripwire_triggered = output_info, tripwire_triggered


class _Generic:
    def __class_getitem__(cls, item):
        return cls


class RunContextWrapper(_Generic):
    def __init__(self, context):
        self.context = context
        self.usage = Usage()


class Usage:
    def __init__(self, requests=1, input_tokens=100, output_tokens=40):
        self.requests, self.input_tokens, self.output_tokens = requests, input_tokens, output_tokens
        self.total_tokens = input_tokens + output_tokens


class ModelSettings:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class RunHooks(_Generic):
    async def on_agent_start(self, context, agent):
        pass

    async def on_agent_end(self, context, agent, output):
        pass


class RunResult:
    def __init__(self, output, wrapper):
        self.final_output, self.context_wrapper = output, wrapper


class FunctionTool:
    def __init__(self, fn, failure_error_function=None):
        self.fn, self.err, self.name = fn, failure_error_function, fn.__name__

    async def __call__(self, ctx, **kwargs):
        try:
            return await self.fn(ctx, **kwargs)
        except Exception as e:
            if self.err is None:
                raise
            return self.err(ctx, e)


def function_tool(fn=None, **opts):
    if fn is None:
        return lambda f: FunctionTool(f, opts.get("failure_error_function"))
    return FunctionTool(fn)


class Agent(_Generic):
    def __init__(self, name, instructions="", model=None, model_settings=None, tools=(), output_type=None,
                 input_guardrails=(), output_guardrails=(), handoffs=()):
        self.name, self.instructions, self.model = name, instructions, model
        self.tools, self.output_type = list(tools), output_type
        self.input_guardrails, self.output_guardrails = list(input_guardrails), list(output_guardrails)


def _guardrail_decorator(fn=None, *, name=None):
    def wrap(f):
        return f
    return wrap(fn) if fn else wrap


input_guardrail = output_guardrail = _guardrail_decorator

SCRIPT: dict = {}   # agent name -> async fn(task, wrapper, agent) -> output
CALLS: list = []    # (agent name, task) log for assertions


class Runner:
    @staticmethod
    async def run(agent, inp, context=None, max_turns=10, hooks=None, session=None):
        wrapper = RunContextWrapper(context)
        CALLS.append((agent.name, inp if isinstance(inp, str) else str(inp)))
        if callable(agent.instructions):
            agent.instructions(wrapper, agent)  # exercise dynamic instructions
        for g in agent.input_guardrails:
            out = await g(wrapper, agent, inp)
            if out.tripwire_triggered:
                raise InputGuardrailTripwireTriggered(out)
        if hooks:
            await hooks.on_agent_start(wrapper, agent)
        output = await SCRIPT[agent.name](inp, wrapper, agent)
        for g in agent.output_guardrails:
            out = await g(wrapper, agent, output)
            if out.tripwire_triggered:
                raise OutputGuardrailTripwireTriggered(out)
        if hooks:
            await hooks.on_agent_end(wrapper, agent, output)
        return RunResult(output, wrapper)


@contextlib.contextmanager
def trace(name, **kwargs):
    yield


@contextlib.contextmanager
def custom_span(name, **kwargs):
    yield


class SQLiteSession:
    def __init__(self, session_id, db_path=None):
        self.session_id = session_id
