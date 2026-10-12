# Person A — Agents & Orchestration: Owner's Guide

You own the **LLM layer**: every agent, its prompt, the guardrails, and the workflow that wires the five
orchestration patterns together. Person B owns the deterministic layer underneath (tools, services, data, UI).

---

## 1. What you own

| Area | File | What it contains |
|---|---|---|
| Prompts | `src/rdi/agent_team/prompts.py` | All instructions, versioned (`PROMPT_VERSION`, attached to every trace) |
| Agents | `src/rdi/agent_team/planner.py` | Research Planner — prompt chaining step 1 |
| | `src/rdi/agent_team/specialists.py` | Technical / Market / Risk workers |
| | `src/rdi/agent_team/orchestrator.py` | Orchestrator + `delegate_*` tools (budget enforced in code) |
| | `src/rdi/agent_team/writer.py`, `critic.py` | Generator and evaluator |
| | `src/rdi/agent_team/assistant.py` | Follow-up chat agent |
| | `src/rdi/agent_team/scope_classifier.py` | LLM classifier for the input guardrail |
| | `src/rdi/agent_team/settings.py`, `registry.py` | Model settings per model family; agent table |
| Guardrails | `src/rdi/guardrails/input_guardrails.py` | Deterministic + LLM input guardrails |
| | `src/rdi/guardrails/output_guardrails.py` | Grounding guardrails for findings and reports |
| Workflow | `src/rdi/workflows/pipeline.py` | **Top level — read first.** Six steps, one call each |
| | `src/rdi/workflows/parallel_research.py` | Parallelization |
| | `src/rdi/workflows/orchestration.py` | Orchestrator-workers step |
| | `src/rdi/workflows/evaluator_optimizer.py` | Writer ⇄ Critic loop with 3 stop conditions |
| | `src/rdi/workflows/hitl.py` | HITL gate + reviewer decision |
| | `src/rdi/workflows/chat.py` | Session memory |
| Runtime | `src/rdi/runtime.py`, `src/rdi/context.py` | `safe_run` retries, timeline hooks, token usage, step timings |
| Tests | `tests/offline/scenarios.py`, `tests/test_agent_layer.py` | 14 offline scenarios (fake SDK) |
| Tools | `scripts/eval_agents.py`, `scripts/show_agents.py` | Live prompt evaluation; agent table for slides |

## 2. Contract with Person B

| You use from B | B uses from you |
|---|---|
| `tools.py`: `RESEARCH_TOOLS`, `compare_sources`, `retrieve_evidence`, `check_claim_support`, `publish_report`, `scrape_page` | `workflows.pipeline.run_research(question, search_outage=, draft_fault=)` → `PipelineResult` |
| `services/evidence.py`: `validate_findings`, `validate_report` | `workflows.pipeline.decide_approval(id, approved, reviewer, note)` |
| `services/policy.py`: `decide_path`, `post_report_escalation` | `workflows.chat.chat(message, session_id, run_id)` |
| `workflows/routing.py`: `route_subquestions` (specialist names must match `SPECIALISTS`) | `PipelineResult.metrics` (new field) |

**Shared files** (`models.py`, `config.py`): agree before changing. Changes made in this round, which B must know about:
- `models.py`: `PipelineResult.metrics` added (default `{}` — non-breaking).
- `services/approvals.py`: `ApprovalQueue(db_path=None)` now reads `config.APPROVAL_DB` at call time (testability fix).

## 3. The five patterns — how they work, where, how to prove them

| Pattern | Who decides | Code | Proven by scenario test | What to show live |
|---|---|---|---|---|
| Prompt chaining | fixed sequence | `pipeline.py` step 1 → every later step consumes `ResearchPlan` | `happy_path` | Plan JSON panel; `step:plan` span |
| Routing | **code** | `services/policy.decide_path` + `routing.route_subquestions` | `routing_code_rules` | Routing table with the code-added `SQ-RISK`; lookup question → *quick* path |
| Parallelization | code | `parallel_research.py` (`asyncio.gather`, semaphore, `return_exceptions`) | `parallel_fan_out`, `branch_failure_degrades_gracefully` | Timeline: 3 × `start` before any `finish`; overlapping spans in trace |
| Orchestrator-workers | **LLM** | `agent_team/orchestrator.py` + `workflows/orchestration.py` | `orchestrator_delegates`, `delegation_budget_enforced` | `delegation` events; nested specialist runs inside the orchestrator span |
| Evaluator-optimizer | code loop, LLM judge | `evaluator_optimizer.py` | `evaluator_rejects_then_approves`, `evaluator_stagnation_escalates` | Iteration panel: revise → approve with scores |

**Evaluator stop conditions** (all in code): approved (no validator major issue + verdict approve + score ≥ 8), max
iterations (3 full / 2 quick), stagnation (same major issues twice in a row). The best draft is kept, not the last.

**Recovery matrix** (`runtime.safe_run`):

| Failure | Behaviour |
|---|---|
| Input guardrail trip | stop immediately → status `blocked` |
| Output guardrail trip | specialists: retry with the guardrail's findings; writer: next loop iteration with feedback |
| Invalid structured output (`ModelBehaviorError`) | retry with the validation error as feedback |
| `MaxTurnsExceeded` | retry with a tighter tool budget |
| API error / timeout | exponential backoff, retry |
| A parallel branch fails | run continues with the other branches |
| Orchestrator fails | report written from parallel findings only |
| Critic fails | deterministic validator alone decides |

## 4. Tuning workflow (Tue–Wed)

1. Wait for Person B's new `corpus.json`, then replace `CASES` in `scripts/eval_agents.py` with questions from it.
2. Baseline: `python scripts/eval_agents.py` → `outputs/eval_<time>.md`.
3. Change **one** prompt in `prompts.py`, bump `PROMPT_VERSION` (`a-1.1`, …), re-run, compare scores.
4. Open the failing runs in the OpenAI Traces dashboard (filter by run id) to see *why*.
5. Stop when every case scores full marks twice in a row. Commit each improvement separately.

| Agent | Target | If it fails, try |
|---|---|---|
| Planner | 2–4 sub-questions, ≥ 2 tracks, correct impact | Add an example of a good sub-question to `PLANNER` |
| Specialists | ≥ 2 evidence items each, no repeated `save_evidence` rejections | Stress "copy the quote exactly"; lower the tool budget |
| Orchestrator | delegates only on real gaps; records conflicts | Tighten the 3 delegation conditions |
| Writer | no guardrail rejections; calibrated confidence | Remind it to cite only ids from the evidence table |
| Critic | approves good reports in ≤ 2 iterations | Make the scoring bands stricter/looser |

## 5. Your demo script (scenarios 1, 4, 5, 6, 9, 12)

| # | Do | Point at | Say |
|---|---|---|---|
| 1 | Run the CodePilot-style example | Status ✅, report with `[E#]` citations | "Every claim links to a verbatim quote from a page we actually fetched." |
| 4 | Same run → timeline | 3 `parallel start` lines before `finish` | "Independent sub-questions run concurrently with `asyncio.gather`; a failed branch doesn't kill the run." |
| 5 | Migration example → Findings panel | `orchestrator_review.delegations`, `delegation` events | "Here the LLM decides who to call; Python caps it at 3 delegations." |
| 6 | Fault = `unsupported_claim` | Iteration 1 *revise* (unsupported_number), iteration 2 *approve* | "The critic plus a deterministic validator caught a number that no source contains." |
| 9 | Fault = `invented_citation` | Iteration 1 blocked by output guardrail (E99) | "The draft never reached the critic — the guardrail rejected a citation that doesn't exist." |
| 12 | OpenAI Traces → group = run id | `step:*` spans, nested agent/tool spans | "One trace per run, tagged with the prompt version." |

Keep screenshots of each as a backup in case the API is slow during the presentation.

## 6. Questions you should be ready to answer

**Why is routing done in code and not by an LLM?** Routing decides which safety checks run (risk review, human
approval). It must be deterministic and auditable: the same plan always produces the same routes. The LLM only labels
each sub-question's track, constrained to a `Literal` by the schema.

**Then where does the LLM decide?** Planning (how to decompose), orchestration (which worker fills which gap),
critique, and the scope classifier. Those need judgment; none of them can grant permissions.

**What stops the model from inventing sources?** Four layers: `extract_claims` returns verbatim sentences;
`save_evidence` rejects any quote not found in a fetched page; the output guardrail blocks unknown evidence ids; the
validator flags numbers not present in any cited quote. The prompt asks for honesty, but the code enforces it.

**Why explicit `delegate_*` tools instead of `agent.as_tool()`?** So the delegation budget, error handling and logging
live in Python. With `as_tool`, a worker failure could crash the orchestrator and the budget would be prompt-only.

**How does the evaluator loop avoid running forever?** Three stop conditions in code: approved, max iterations, and
stagnation detection. If it ends with unresolved major issues, the report goes to a human instead of being published.

**What happens if the critic approves something bad?** It can't publish anything. Approval requires zero
*deterministic* major issues as well, and `publish_report` re-validates citations before writing the file.

**What if a web page contains a prompt injection?** The page is sanitised before the LLM sees it (instruction sentences
redacted), flagged, its quality capped at 0.10, and the output guardrail blocks findings that rely only on flagged sources.

**How is memory handled?** Within a run: `ResearchContext` (local, never sent to the model). Across chat turns:
`SQLiteSession`, keyed by the browser session.

**How do you know the agent layer works?** 14 offline scenario tests exercise the real pipeline with scripted agents
(every pattern, guardrail and recovery path). Breaking a rule (e.g. raising the delegation budget) makes a test fail.
Live quality is measured with `scripts/eval_agents.py`.

## 7. Commands

```bash
pytest -q                                   # unit tests + 14 agent-layer scenarios (no API key)
python tests/offline/scenarios.py           # readable scenario table
python scripts/eval_agents.py               # live evaluation (API key)
python scripts/show_agents.py               # agent table for slides
```

## 8. If something breaks with the real SDK

| Symptom | Fix |
|---|---|
| Strict JSON-schema error on an output type | `output_type=AgentOutputSchema(Model, strict_json_schema=False)` in that agent's file |
| `TypeError` in `TimelineHooks` | hook signatures differ by SDK version — the hooks already accept `*args`; if needed, delete the `hooks=` argument in `runtime.run_agent` |
| `temperature` not supported | set a reasoning model in `.env`; `settings.model_settings` already drops temperature for o-series / gpt-5 |
| Guardrail runs after the agent output | newer SDKs run input guardrails in parallel; the planner output is discarded on a trip either way |
