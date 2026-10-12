# Step-by-step roadmap (Mon 12 Oct → deadline Sat 17 Oct 2026)

The skeleton already implements every requirement. Your job is to **run it, make it yours, harden it,
and rehearse the demo.** Do the steps in order; each ends with a checkpoint you can verify.

---

## Step 0 — Setup (Mon, 1 h, everyone)
1. Create a GitHub repo, push this folder. Add teammates.
2. `python -m venv .venv`, `pip install -r requirements.txt`, `cp .env.example .env`, add `OPENAI_API_KEY`.
3. ✅ Checkpoint: `pytest -q` → all green. `python tests/offline/scenarios.py` → 14/14 scenarios passed.

## Step 1 — First live run (Mon, 1–2 h)
1. `python app.py`, run Example 3 (quick path), then Example 1 (full path).
2. Open https://platform.openai.com/traces and find the run (group id = run id).
3. If something errors on startup, it's almost always an SDK-version detail — see *Known adjustments* below.
4. ✅ Checkpoint: one run reaches “Published” and one reaches “Waiting for human approval”.

## Step 2 — Make the data yours (Mon–Tue, owner: Data person)
Three teams do Project 3, so **your corpus and scenarios must be different**.
1. Pick your own decision domain (e.g. *“Should our university adopt an LMS”*, *“Which EV charging vendor”*).
2. Rewrite `data/corpus.json`: 12–16 fictional pages. Keep the deliberate traps:
   - 1 page with an injected instruction (scenario 7/injection),
   - 1 vendor-marketing page that **contradicts** a high-quality study (orchestrator conflicts),
   - 1 `"simulate_failure": "always"` page and 1 `"once"` page (scenario 10),
   - a forum/blog page (low quality).
3. Update `EXAMPLES` in `app.py` and `SENSITIVE_KEYWORDS` in `config.py`.
4. ✅ Checkpoint: example questions retrieve the right pages (check the timeline).

## Step 3 — Prompt tuning per agent (Tue, split by agent)
Edit only `agent_team/prompts.py` and measure with `python scripts/eval_agents.py` (see `docs/person-a/GUIDE.md` §4):
- **Planner:** produces 2–4 sub-questions across ≥2 tracks; impact level sensible.
- **Specialists:** save ≥2 evidence items each; no rejected `save_evidence` loops.
- **Orchestrator:** calls a worker only when there is a real gap; records conflicts.
- **Writer/Critic:** loop normally ends in 1–2 iterations on clean runs.
✅ Checkpoint: Example 1 & 2 finish in < 3 minutes with no `recovery` events.

## Step 4 — Reliability hardening (Wed, owner: Backend person)
1. Kill your internet during a run → UI must show a clean failure, not a stack trace.
2. Put an invalid model name in `.env` → status ❌ Failed with a readable message.
3. Add tests for anything you changed in `services/` (pattern in `tests/test_deterministic.py`).
✅ Checkpoint: `pytest -q` green; no unhandled exception reaches Gradio.

## Step 5 — Rehearse the 12 scenarios (Wed–Thu, everyone)
Use the table in README §Demo scenarios. For each one write down: input, expected status, which panel/
trace span proves it. Take screenshots as backup in case the live API is slow during the presentation.
✅ Checkpoint: all 12 reproduced twice in a row.

## Step 6 — Bonus: explain RAG + source-quality scoring (Thu, owner: one person)
Already implemented: `services/bm25.py`, `EvidenceStore.retrieve`, `services/source_quality.py`.
Prepare 2 slides: how BM25 retrieval works, how quality scores feed the writer, critic and validator
(e.g. the injected blog is capped at 0.10 and can't support a finding).

## Step 7 — Presentation & README (Fri)
Slides: problem → architecture diagram → code vs LLM orchestration table → the 5 patterns (each with the
exact code location) → guardrails → HITL → live demo → bonus → lessons learned.
✅ Checkpoint: full dry run in ≤ the allowed time. Submit Sat 17 Oct.

---

## Team split (2 people)
Split follows the architecture: **A = LLM layer (purple), B = Python layer (teal).**

| | A — Agents & orchestration | B — Rules, data, UI |
|---|---|---|
| Files owned | `agent_team/`, `guardrails/`, `runtime.py`, `context.py`, `workflows/` (except `routing.py`), `scripts/`, `tests/offline/` — see `docs/person-a/GUIDE.md` | `services/`, `tools.py`, `workflows/routing.py`, `data/corpus.json`, `app.py`, `tests/` |
| Shared (change only after agreeing) | `models.py`, `config.py` | `models.py`, `config.py` |
| Scenarios to own in the demo | 1 happy path, 4 parallel, 5 orchestrator, 6 evaluator, 9 output guardrail, 12 trace | 2 multi-step tools, 3 routing, 7 input guardrail, 8 blocked tool, 10 failure/recovery, 11 HITL |
| Slides | 5 patterns, LLM-orchestrated decisions, prompts | code-orchestrated decisions, guardrails, anti-hallucination, bonus (RAG + quality) |

| Day | A | B |
|---|---|---|
| Mon 12 | Together: Step 0–1 setup + first live run, **choose your own topic** | (same) |
| Tue 13 | Tune Planner + specialist prompts on the new topic | Write new `corpus.json` (keep the traps), update examples, keywords, tests |
| Wed 14 | Orchestrator + writer/critic behaviour, faults 6 & 9, trace screenshots | Reliability hardening (Step 4), UI polish, approvals flow |
| Thu 15 | Swap: review and run B's part until you can explain it | Swap: review and run A's part until you can explain it |
| Fri 16 | Slides for your half, full dry run of all 12 scenarios | Slides for your half, README, full dry run |
| Sat 17 | Submit | Submit |

Git: one branch per person (`a/agents`, `b/services`), merge to `main` daily after `pytest -q` passes.

## Known adjustments (SDK version differences)
The code targets `openai-agents` ≥ 0.3. If your installed version differs:
- **Strict JSON schema error on an output model** → wrap it: `output_type=AgentOutputSchema(DecisionReport, strict_json_schema=False)`.
- **`gr.Chatbot(type="messages")` error** (older Gradio) → upgrade Gradio to ≥4.44.
- **Model not found** → change `RDI_MODEL_FAST/SMART` in `.env`.
