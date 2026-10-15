"""Guardrails.

| Guardrail                       | Kind   | Attached to              | Blocks                                              |
|---------------------------------|--------|--------------------------|-----------------------------------------------------|
| deterministic_input_guardrail   | input  | Planner, Assistant       | prompt injection, secret requests, empty/huge input |
| scope_input_guardrail           | input  | Planner                  | off-topic, harmful, secret-seeking (LLM classifier) |
| findings_grounding_guardrail    | output | 3 specialists            | findings citing evidence that was never saved       |
| report_grounding_guardrail      | output | Report Writer            | invented citations, flagged-only claims, echoed     |
|                                 |        |                          | injected instructions                               |
Tool-level safety (URL policy, verbatim quotes, approval before publish) is in rdi/tools.py.
"""
from rdi.guardrails.input_guardrails import deterministic_input_guardrail, scope_input_guardrail
from rdi.guardrails.output_guardrails import findings_grounding_guardrail, report_grounding_guardrail

__all__ = ["deterministic_input_guardrail", "scope_input_guardrail",
           "findings_grounding_guardrail", "report_grounding_guardrail"]
