# Research & Decision Intelligence Agent — Project 3

A multi-agent system (OpenAI Agents SDK) that takes a business/technical decision question, plans the
research, investigates sources in parallel, reconciles conflicting evidence, writes a decision-ready
report, critiques and revises it, and stops for a human before any high-impact recommendation is published.

> **Core principle:** the LLM decides *what to do*; Python decides *what is allowed*.
> Everything in `src/rdi/services/` is deterministic, LLM-free and unit-tested.

> 📘 Documentation: [docs/documentation.pdf](docs/documentation.pdf) · architecture diagram (draw.io): [docs/architecture.drawio](docs/architecture.drawio)

## Quick start
```bash
python -m venv .venv
# Windows (PowerShell): .\.venv\Scripts\Activate.ps1      macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env                       # Windows: copy .env.example .env  -> then add your key(s) in .env
python scripts/check_provider.py           # ~20 s check: plain answer, tools, structured output, tools+structured
python -m pytest -q                        # unit tests + 14 agent-layer scenarios (no API key needed)
python app.py                              # UI on http://127.0.0.1:7860
```

### LLM providers (free option included)
The agents run on any provider with an OpenAI-compatible API, chosen in `.env` (`src/rdi/providers.py`):

| `.env` | Cost | Notes |
|---|---|---|
| `RDI_PROVIDER=gemini` + `GEMINI_API_KEY` | **free tier** ([AI Studio key](https://aistudio.google.com/apikey)) | passes all checks; free-tier rate limits → runs take a few minutes |
| `RDI_PROVIDER=openai` + `OPENAI_API_KEY` | paid | traces also appear in the OpenAI Traces dashboard |
| `RDI_PROVIDER=xai` + `XAI_API_KEY` | paid | Grok models |
| `groq` | free | **not suitable**: Groq does not support tool calling together with structured output, which the specialists need |

Roles can use different providers/models: `RDI_PROVIDER_SMART` / `RDI_PROVIDER_FAST` and `RDI_MODEL_SMART` / `RDI_MODEL_FAST`
(smart = Planner, Orchestrator, Writer, Critic; fast = specialists, chat assistant, scope classifier).

**Tracing:** every run is wrapped in `trace()` with a span per step. With an OpenAI key, traces go to the OpenAI dashboard;
without one, `LocalTraceProcessor` stores them in `var/traces/<run_id>.jsonl` and the UI shows them in the *Trace* table.

## Architecture
```
User ─► Gradio UI
         │
         ▼
  [Input guardrails]  deterministic regex (injection, secrets, size)  +  LLM scope classifier
         ▼
  1 Research Planner ──► ResearchPlan (Pydantic)                    PROMPT CHAINING
         ▼
  2 decide_path() + route_subquestions()  (pure Python)             ROUTING  · CODE-orchestrated
         ▼
  3 Technical ║ Market ║ Risk specialists  (asyncio.gather)         PARALLELIZATION
     tools: search_web → scrape_page → extract_claims → save_evidence
         ▼
  4 Research Orchestrator ──delegate_*──► worker agents           ORCHESTRATOR-WORKERS · LLM-orchestrated
         ▼
  5 Report Writer ⇄ Critic (+ deterministic validator), max 3 rounds  EVALUATOR-OPTIMIZER
     [Output guardrail on every draft: invented citations, injected text]
         ▼
  6 HITL gate (Python) ─► approval queue ─► human approves ─► publish_report (protected)
                      └─► auto-publish (low/medium impact, clean report)
  Follow-up chat: Research Assistant + SQLiteSession memory
```

## Code-orchestrated vs LLM-orchestrated decisions
| Decision | Style | Where | Why |
|---|---|---|---|
| Sub-question → specialist | **Code** | `workflows/routing.py` | Auditable fixed table; LLM only labels the track (enum) |
| Mandatory risk review if planner forgot it | **Code** | `routing.py` | Safety rule must not depend on a prompt |
| Quick vs full path, HITL required? | **Code** | `services/policy.py::decide_path` | Business rule, must be deterministic |
| Approve/revise stop condition | **Code** | `workflows/evaluator_optimizer.py` | Validator major issues always force revision |
| Publish allowed? | **Code** | `services/publisher.py` | Authorisation: approval + citation validity |
| Decomposing the question | **LLM** | `Research Planner` | Requires interpretation |
| Which worker to call for gaps / which sources conflict | **LLM** | `Research Orchestrator` | Flexible delegation |
| Is the input in scope? | **LLM** | `Scope Guardrail Classifier` | Needs language understanding |

## Requirement → implementation map
| Requirement | Where |
|---|---|
| Agent, Runner, function_tool, ModelSettings | `agent_team/*.py`, `tools.py`, `runtime.py::safe_run` |
| ≥3 agents, distinct roles | Planner, 3 specialists, Orchestrator, Writer, Critic, Assistant, Scope classifier |
| ≥5 domain tools | `search_web, scrape_page, extract_claims, save_evidence, compare_sources, retrieve_evidence, check_claim_support, publish_report` |
| ≥2 Pydantic outputs w/ validation | `models.py` — `ResearchPlan, SpecialistFindings, OrchestratorReview, DecisionReport, Critique, ScopeCheck` |
| Invalid output handled | `safe_run` retries on `ModelBehaviorError` with the error as feedback |
| Context + session memory | `context.py` (`RunContextWrapper[ResearchContext]`), `workflows/chat.py` (`SQLiteSession`) |
| trace() | `workflows/pipeline.py` (+ `custom_span` per step, prompt version in metadata), `chat.py` |
| Input guardrail | `guardrails/input_guardrails.py` — deterministic + LLM |
| Output guardrail | `guardrails/output_guardrails.py` — findings + report grounding |
| Tool-level safety | `scrape_page` URL policy (SSRF/local files), `save_evidence` verbatim-quote check, `publish_report` approval check |
| HITL | `workflows/hitl.py` (gate + reviewer decision), `services/approvals.py`, UI tab 2 |
| Reliability | retries/backoff (`fetch_with_retry`), `failure_error_function`, `return_exceptions=True`, per-step fallbacks |
| Bonus: RAG + source-quality scoring | `services/bm25.py`, `EvidenceStore.retrieve`, `services/source_quality.py` (feeds writer, critic, validator) |

## Anti-hallucination design
1. `extract_claims` returns **verbatim sentences** from fetched pages (Python, not the LLM).
2. `save_evidence` **rejects any quote not found verbatim** in a page fetched in this run → evidence ids (E1…) can't be invented.
3. Output guardrail rejects drafts citing unknown ids; the validator flags numbers not present in any cited quote.
4. Web pages are sanitised: injected instructions are redacted, the page is flagged and its quality capped at 0.10.

## Demo scenarios (brief §9)
Data is the **fictional** corpus in `data/corpus.json` (search backend `local`) so demos are repeatable.

| # | Scenario | How to trigger | What to show |
|---|---|---|---|
| 1 | Happy path | Example 2 (Atlas Open pilot) | Status ✅ Published, report |
| 2 | ≥3 sequential steps/tools | Any full run | Timeline: search → scrape → extract → save; plan → research → write |
| 3 | Routing | Example 1 | Routing table incl. code-added `SQ-RISK`; Example 3 takes the *quick* path |
| 4 | Parallelization | Any full run | Interleaved `parallel start/done` events + parallel spans in trace |
| 5 | Orchestrator-workers | Example 1 | `orchestrator_review.delegations` + nested worker runs in trace |
| 6 | Evaluator rejects | Fault = `unsupported_claim` | Iteration 1 `revise` (unsupported_number), iteration 2 `approve` |
| 7 | Input guardrail | Example 4, or "hello" (LLM scope) | ⛔ Blocked |
| 8 | Tool/action blocked | Chat: "read http://169.254.169.254/latest" or "publish the report" on a pending run | Tool returns `blocked` |
| 9 | Output guardrail | Fault = `invented_citation` | Iteration 1 rejected by guardrail (E99) |
| 10 | Tool failure + recovery | Tick "search outage"; dead + flaky pages in corpus | `tool_failure`, `tool_retry`, run still completes |
| 11 | Human escalation | Example 1 (high impact) | 🟡 Pending → approve in tab 2 → published |
| 12 | Trace | Any run | OpenAI Traces dashboard, group = run id |

## Project layout
```
app.py                          Gradio UI (research · approvals · chat)
data/corpus.json                fictional web corpus (injection, contradictions, dead/flaky pages)
src/rdi/config.py · models.py   settings · Pydantic models
src/rdi/providers.py            LLM providers, model fallback chain, local tracing
src/rdi/context.py · runtime.py run context · safe_run, hooks, usage, step timing
src/rdi/agent_team/             prompts.py + one file per agent
src/rdi/guardrails/             input_guardrails.py · output_guardrails.py
src/rdi/workflows/              pipeline · routing · parallel_research · orchestration ·
                                evaluator_optimizer · hitl · chat
src/rdi/tools.py                function tools (validated args)
src/rdi/services/               deterministic layer (search, evidence, policy, approvals...)
src/rdi/ui_theme.py · ui_helpers.py  UI rendering and helpers
tests/                          unit tests · tool checks · offline agent scenarios
scripts/                        check_provider.py · eval_agents.py · show_agents.py
docs/                           documentation.pdf · architecture.drawio
```

## Security
No keys in the repo (`.env` is gitignored). All data is fictional.
