"""Run context shared by every agent, tool and guardrail in one research run.

Passed to the SDK as `Runner.run(..., context=ctx)` and reached inside tools/guardrails as
`RunContextWrapper[ResearchContext].context`. It is LOCAL Python state - it is never sent to
the LLM. It carries:
  * the evidence store (the only source of citable evidence),
  * the event timeline shown in the UI (complements the OpenAI trace),
  * metrics (token usage, step timings) and demo fault-injection flags.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from rdi.services.evidence import EvidenceStore


@dataclass
class ResearchContext:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    question: str = ""
    user_role: str = "analyst"
    evidence: EvidenceStore = field(default_factory=EvidenceStore)

    # Decisions taken by Python during the run
    requires_approval: bool = False
    report: object | None = None            # final DecisionReport once written
    published_path: str | None = None
    delegations_used: int = 0               # orchestrator budget, enforced in code

    # Demo fault injection (clearly labelled in the UI)
    fault_search_outage: bool = False
    draft_fault: str = "none"               # "none" | "invented_citation" | "unsupported_claim"
    _search_calls: int = 0

    # Observability
    events: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    step_seconds: dict = field(default_factory=dict)
    _t0: float = field(default_factory=time.time)

    def log(self, kind: str, message: str, **data) -> None:
        self.events.append({"t": round(time.time() - self._t0, 2), "kind": kind, "message": message, **data})

    def metrics(self) -> dict:
        return {
            "duration_s": round(time.time() - self._t0, 1),
            "steps_s": dict(self.step_seconds),
            "usage": dict(self.usage),
            "evidence_items": len(self.evidence.items),
            "pages_read": len(self.evidence.pages),
            "delegations": self.delegations_used,
        }


# In-memory registry so the follow-up chat and the approval screen can reach a run's evidence.
RUNS: dict[str, ResearchContext] = {}
