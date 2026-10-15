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

CORPUS_PATH = Path(os.getenv("RDI_CORPUS_PATH") or DATA_DIR / "corpus.json")  # tests can point this elsewhere
SESSION_DB = str(VAR_DIR / "sessions.db")
APPROVAL_DB = str(VAR_DIR / "approvals.db")

# --- LLM providers -------------------------------------------------------------------------
# Agents come in two roles, and each role can use a different provider:
#   smart = Planner, Orchestrator, Report Writer, Critic   (large prompts, quality matters)
#   fast  = 3 specialists, Research Assistant, Scope classifier (many small calls)
# Providers: "openai" (paid) | "gemini" (free tier) | "groq" (free tier, small token limits) | "xai" (Grok, paid)
# Non-OpenAI providers are reached through their OpenAI-compatible endpoints (see rdi/providers.py).
PROVIDER_PRESETS = {
    "openai": {"base_url": None, "key_env": "OPENAI_API_KEY",
               "smart": "gpt-4.1", "fast": "gpt-4.1-mini", "parallel": 4, "page_chars": 6000},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "key_env": "GEMINI_API_KEY",
               "smart": "gemini-3.8-flash", "fast": "gemini-3.6-flash", "parallel": 1, "page_chars": 6000},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
             "smart": "openai/gpt-oss-120b", "fast": "openai/gpt-oss-120b", "parallel": 1, "page_chars": 2500},
    "xai": {"base_url": "https://api.x.ai/v1", "key_env": "XAI_API_KEY",
            "smart": "grok-4", "fast": "grok-4-fast", "parallel": 2, "page_chars": 6000},
}


def _provider(var: str, default: str) -> str:
    name = (os.getenv(var) or default).strip().lower()
    if name not in PROVIDER_PRESETS:
        raise ValueError(f"{var} must be one of {sorted(PROVIDER_PRESETS)}, got '{name}'")
    return name


PROVIDER = _provider("RDI_PROVIDER", "openai")                    # default for both roles
PROVIDER_SMART = _provider("RDI_PROVIDER_SMART", PROVIDER)
PROVIDER_FAST = _provider("RDI_PROVIDER_FAST", PROVIDER)
ROLE_PROVIDER = {"smart": PROVIDER_SMART, "fast": PROVIDER_FAST}
PROVIDER_LABEL = PROVIDER_SMART if PROVIDER_SMART == PROVIDER_FAST else f"{PROVIDER_SMART} (smart) + {PROVIDER_FAST} (fast)"


def provider_key(name: str) -> str:
    return os.getenv(PROVIDER_PRESETS[name]["key_env"], "")


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")   # optional with other providers: only used to upload traces

MODEL_SMART = os.getenv("RDI_MODEL_SMART") or PROVIDER_PRESETS[PROVIDER_SMART]["smart"]
MODEL_FAST = os.getenv("RDI_MODEL_FAST") or PROVIDER_PRESETS[PROVIDER_FAST]["fast"]

# --- Automatic model fallback -------------------------------------------------------------
# When a model fails (free-tier quota/429, overloaded, not found, cannot do tools+structured output)
# the next model in the chain is used automatically (rdi/providers.py::FallbackModel).
# RDI_FALLBACK_MODELS: comma list of "provider:model" or "model" (= same provider as the role); "none" disables.
DEFAULT_FALLBACKS = {
    # each Gemini model has its own free-tier quota -> chaining them multiplies the free budget
    "gemini": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    "groq": ["gemini:gemini-3.6-flash", "gemini:gemini-3.5-flash-lite"],  # Groq cannot do tools+structured output
    "openai": [], "xai": [],
}


def _parse_entry(entry: str, default_provider: str) -> tuple[str, str]:
    entry = entry.strip()
    if ":" in entry and entry.split(":", 1)[0].strip().lower() in PROVIDER_PRESETS:
        prov, name = entry.split(":", 1)
        return prov.strip().lower(), name.strip()
    return default_provider, entry


def role_chain(role: str) -> list[tuple[str, str]]:
    """Ordered (provider, model) list for a role: the primary model first, then the fallbacks."""
    provider = ROLE_PROVIDER[role]
    primary = (provider, MODEL_SMART if role == "smart" else MODEL_FAST)
    raw = os.getenv("RDI_FALLBACK_MODELS")
    if raw is not None and raw.strip().lower() in ("none", "off", "false", "0"):
        entries = []
    elif raw and raw.strip():
        entries = [_parse_entry(e, provider) for e in raw.split(",") if e.strip()]
    else:
        entries = [_parse_entry(e, provider) for e in DEFAULT_FALLBACKS.get(provider, [])]
    chain = [primary]
    for prov, name in entries:
        if (prov, name) not in chain and (prov == provider or provider_key(prov)):  # skip providers without a key
            chain.append((prov, name))
    return chain
_USED = [PROVIDER_PRESETS[n] for n in {PROVIDER_SMART, PROVIDER_FAST}]
TRACE_DIR = VAR_DIR / "traces"

SEARCH_BACKEND = os.getenv("RDI_SEARCH_BACKEND", "local")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Evaluator-optimizer loop bounds
MAX_CRITIC_ITERATIONS = int(os.getenv("RDI_MAX_CRITIC_ITERATIONS", "3"))
CRITIC_PASS_SCORE = int(os.getenv("RDI_CRITIC_PASS_SCORE", "8"))

# Parallelism / robustness
MAX_PARALLEL = int(os.getenv("RDI_MAX_PARALLEL") or min(p["parallel"] for p in _USED))  # 1 on free tiers
AGENT_MAX_TURNS = 14
STEP_RETRIES = 1                  # extra attempts on invalid structured output / model error
FETCH_RETRIES = 2                 # retries for flaky page fetches
MAX_PAGE_CHARS = min(p["page_chars"] for p in _USED)  # page text handed to the LLM (smaller for Groq)

# Tool-level safety: scraping policy
BLOCKED_DOMAINS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"}
ALLOWED_SCHEMES = {"https", "http"}

# Decisions in these domains always need a human before finalising
SENSITIVE_KEYWORDS = {
    "layoff", "lay off", "fire ", "medical", "diagnos", "legal", "lawsuit",
    "invest", "acquisition", "acquire", "merger", "security breach",
    # university / LMS topic: decisions that expose student data or touch staff jobs need a human
    "student records", "student data", "grade data", "personal data", "redundan", "staff cuts",
}
