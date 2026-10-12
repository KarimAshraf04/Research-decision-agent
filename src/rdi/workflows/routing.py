"""CODE-ORCHESTRATED routing.

The Planner (LLM) labels each sub-question with a `track` (constrained to a Literal by the
Pydantic schema). Python then maps track -> specialist with a fixed table. Why deterministic?
  * auditable: the same plan always produces the same assignment,
  * safe: an LLM cannot invent a new specialist or skip the risk analysis.
"""
from __future__ import annotations

from rdi.models import ResearchPlan, RouteDecision

SPECIALIST_BY_TRACK = {
    "technical": "Technical Research Specialist",
    "market": "Market Research Specialist",
    "risk": "Risk & Compliance Specialist",
}


def route_subquestions(plan: ResearchPlan) -> list[RouteDecision]:
    routes = [
        RouteDecision(subquestion_id=sq.id, specialist=SPECIALIST_BY_TRACK[sq.track],
                      reason=f"track='{sq.track}' -> {SPECIALIST_BY_TRACK[sq.track]}")
        for sq in plan.subquestions
    ]
    # Safety rule: every non-trivial decision gets a risk perspective, even if the planner forgot it.
    if len(plan.subquestions) > 1 and not any(sq.track == "risk" for sq in plan.subquestions):
        routes.append(RouteDecision(subquestion_id="SQ-RISK", specialist=SPECIALIST_BY_TRACK["risk"],
                                    reason="Rule: no risk sub-question in plan -> mandatory risk review added by code."))
    return routes
