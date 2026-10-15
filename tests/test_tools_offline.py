"""Runs tests/tool_checks.py (real tools, real corpus, FAKE SDK) in a subprocess - same isolation trick as
test_agent_layer.py, so `pytest -q` works whether or not the real openai-agents SDK is installed."""
import json
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).parent / "tool_checks.py"
CHECKS = ["sequential_tools", "blocked_tool", "injection_page", "fabricated_quote_rejected", "dead_page_recovery",
          "flaky_page_recovery", "search_outage_recovery", "argument_validation", "publish_protected"]


@pytest.fixture(scope="module")
def results():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--json"], capture_output=True, text=True, timeout=300)
    assert proc.stdout.strip(), f"tool_checks produced no output:\n{proc.stderr}"
    return {r["scenario"]: r for r in json.loads(proc.stdout.strip().splitlines()[-1])}


@pytest.mark.parametrize("name", CHECKS)
def test_tool_check(results, name):
    r = results[name]
    assert r["passed"], r.get("trace") or r["detail"]
