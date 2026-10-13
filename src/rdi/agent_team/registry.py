"""One table of every agent: used by docs, the eval script and the presentation."""
from rdi.agent_team.assistant import assistant_agent
from rdi.agent_team.critic import critic_agent
from rdi.agent_team.orchestrator import orchestrator_agent
from rdi.agent_team.planner import planner_agent
from rdi.agent_team.scope_classifier import scope_classifier
from rdi.agent_team.specialists import market_agent, risk_agent, technical_agent
from rdi.agent_team.writer import writer_agent

AGENTS = [
    # (agent, role in the system, orchestration pattern)
    (planner_agent, "Decomposes the question into a ResearchPlan", "Prompt chaining - step 1"),
    (technical_agent, "Researches technical sub-questions with verbatim evidence", "Parallelization / worker"),
    (market_agent, "Researches market sub-questions with verbatim evidence", "Parallelization / worker"),
    (risk_agent, "Researches risks; mandatory on every multi-part decision", "Parallelization / worker"),
    (orchestrator_agent, "Decides which worker fills which gap; records conflicts", "Orchestrator-workers (LLM)"),
    (writer_agent, "Writes the decision report from the evidence package", "Evaluator-optimizer - generator"),
    (critic_agent, "Scores the report and lists required fixes", "Evaluator-optimizer - evaluator"),
    (assistant_agent, "Follow-up Q&A with memory; can request publishing", "Session memory"),
    (scope_classifier, "Classifies input scope for the input guardrail", "Guardrail"),
]


def describe() -> str:
    lines = ["| Agent | Model | Tools | Output | Role | Pattern |", "|---|---|---|---|---|---|"]
    for agent, role, pattern in AGENTS:
        tools = ", ".join(getattr(t, "name", "?") for t in agent.tools) or "-"
        out = getattr(agent.output_type, "__name__", "text") if agent.output_type else "text"
        model = getattr(agent.model, "model", agent.model)
        lines.append(f"| {agent.name} | {model} | {tools} | {out} | {role} | {pattern} |")
    return "\n".join(lines)
