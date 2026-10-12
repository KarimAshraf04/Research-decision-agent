"""Central configuration. Everything tunable lives here (read from env / .env)."""
from __future__ import annotations

import os
from pathlib import Path

try:  # optional dependency
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
VAR_DIR = ROOT / "var"          # runtime state (sqlite dbs) - gitignored
OUTPUT_DIR = ROOT / "outputs"   # published reports - gitignored
VAR_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

CORPUS_PATH = DATA_DIR / "corpus.json"
SESSION_DB = str(VAR_DIR / "sessions.db")
APPROVAL_DB = str(VAR_DIR / "approvals.db")

MODEL_FAST = os.getenv("RDI_MODEL_FAST", "gpt-4.1-mini")
MODEL_SMART = os.getenv("RDI_MODEL_SMART", "gpt-4.1")

SEARCH_BACKEND = os.getenv("RDI_SEARCH_BACKEND", "local")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Evaluator-optimizer loop bounds
MAX_CRITIC_ITERATIONS = int(os.getenv("RDI_MAX_CRITIC_ITERATIONS", "3"))
CRITIC_PASS_SCORE = int(os.getenv("RDI_CRITIC_PASS_SCORE", "8"))

# Parallelism / robustness
MAX_PARALLEL = int(os.getenv("RDI_MAX_PARALLEL", "4"))
AGENT_MAX_TURNS = 14
STEP_RETRIES = 1                  # extra attempts on invalid structured output / model error
FETCH_RETRIES = 2                 # retries for flaky page fetches
MAX_PAGE_CHARS = 6000             # truncation of scraped content handed to the LLM

# Tool-level safety: scraping policy
BLOCKED_DOMAINS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"}
ALLOWED_SCHEMES = {"https", "http"}

# Decisions in these domains always need a human before finalising
SENSITIVE_KEYWORDS = {
    "layoff", "lay off", "fire ", "medical", "diagnos", "legal", "lawsuit",
    "invest", "acquisition", "acquire", "merger", "security breach",
}
