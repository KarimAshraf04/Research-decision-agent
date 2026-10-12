"""Runs the offline agent-layer scenarios in a separate process.

A subprocess is used because the scenarios replace the real `agents` SDK with a fake one; keeping
them isolated means `pytest -q` works whether or not the real SDK is installed.
"""
import json
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).parent / "offline" / "scenarios.py"


@pytest.fixture(scope="module")
def scenario_results():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--json"], capture_output=True, text=True, timeout=300)
    assert proc.stdout.strip(), f"scenario runner produced no output:\n{proc.stderr}"
    return {r["scenario"]: r for r in json.loads(proc.stdout.strip().splitlines()[-1])}


SCENARIOS = [
    "happy_path", "routing_code_rules", "parallel_fan_out", "orchestrator_delegates",
    "delegation_budget_enforced", "evaluator_rejects_then_approves", "output_guardrail_blocks_draft",
    "evaluator_stagnation_escalates", "input_guardrail_deterministic", "input_guardrail_llm_scope",
    "specialist_guardrail_retry", "tool_failure_recovery", "branch_failure_degrades_gracefully",
    "hitl_end_to_end",
]


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario(scenario_results, name):
    result = scenario_results[name]
    assert result["passed"], result.get("trace") or result["detail"]
