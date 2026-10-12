"""Print the agent table (name, model, tools, output type, role, pattern) - paste it into slides/README.

    python scripts/show_agents.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from rdi.agent_team.registry import describe  # noqa: E402

print(describe())
