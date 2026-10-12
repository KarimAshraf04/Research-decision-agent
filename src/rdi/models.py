"""Pydantic models.

Two families:
  * LLM OUTPUT models (used as `output_type=` on agents). No default values (keeps the
    strict JSON schema happy); constraints are enforced with Literals + validators.
    If a model returns something invalid, the SDK raises ModelBehaviorError and our
    `safe_run` helper retries with the validation error as feedback.
  * INTERNAL models produced by deterministic Python (evidence, routing, approvals...).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Track = Literal["technical", "market", "risk"]
Confidence = Literal["low", "medium", "high"]
EVIDENCE_ID_RE = re.compile(r"^E\d{1,4}$")


def _clean_evidence_ids(ids: list[str]) -> list[str]:
    cleaned = [i.strip().upper() for i in ids if i and i.strip()]
    bad = [i for i in cleaned if not EVIDENCE_ID_RE.match(i)]
    if bad:
        raise ValueError(f"Evidence ids must look like 'E12'; got {bad}")
    return list(dict.fromkeys(cleaned))  # dedupe, keep order


# --------------------------------------------------------------------------------------
# LLM output models
# --------------------------------------------------------------------------------------
class SubQuestion(BaseModel):
    id: str = Field(description="Identifier 'SQ1', 'SQ2', ...")
    question: str = Field(description="A focused, independently researchable sub-question")
    track: Track = Field(description="Which specialist should research it")
    search_queries: list[str] = Field(description="1-3 concise web search queries")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.fullmatch(r"SQ\d{1,2}", v):
            raise ValueError("id must look like 'SQ1'")
        return v

    @field_validator("question")
    @classmethod
    def _question(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("sub-question too short")
        return v.strip()

    @field_validator("search_queries")
    @classmethod
    def _queries(cls, v: list[str]) -> list[str]:
        v = [q.strip() for q in v if q.strip()][:3]
        if not v:
            raise ValueError("at least one search query is required")
        return v


class ResearchPlan(BaseModel):
    """Output of chain step 1 (Planner)."""

    restated_question: str = Field(description="The decision question, restated precisely")
    decision_type: Literal["build_vs_buy", "vendor_selection", "adoption", "investment", "policy", "other"]
    impact_level: Literal["low", "medium", "high"] = Field(
        description="Business impact if the recommendation is wrong (high = large cost, legal, people or security impact)"
    )
    impact_rationale: str
    subquestions: list[SubQuestion] = Field(description="2-5 sub-questions covering technical, market and risk angles")
    success_criteria: list[str] = Field(description="What a good final answer must contain")

    @field_validator("subquestions")
    @classmethod
    def _subs(cls, v: list[SubQuestion]) -> list[SubQuestion]:
        if not v:
            raise ValueError("plan needs at least one sub-question")
        v = v[:5]
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("sub-question ids must be unique")
        return v


class Finding(BaseModel):
    statement: str = Field(description="One factual statement, supported by the cited evidence")
    evidence_ids: list[str] = Field(description="Evidence ids (e.g. 'E3') returned by save_evidence")
    confidence: Confidence

    @field_validator("evidence_ids")
    @classmethod
    def _ids(cls, v: list[str]) -> list[str]:
        return _clean_evidence_ids(v)


class SpecialistFindings(BaseModel):
    """Output of a worker / specialist research agent."""

    subquestion_id: str
    track: Track
    summary: str
    findings: list[Finding]
    gaps: list[str] = Field(description="What could not be answered with the available sources")
    sources_consulted: list[str] = Field(description="URLs actually opened with scrape_page")


class Conflict(BaseModel):
    description: str
    evidence_ids: list[str]

    @field_validator("evidence_ids")
    @classmethod
    def _ids(cls, v: list[str]) -> list[str]:
        return _clean_evidence_ids(v)


class OrchestratorReview(BaseModel):
    """Output of the LLM-orchestrated gap-filling step."""

    delegations: list[str] = Field(description="Which worker was called and why, one line each")
    conflicts: list[Conflict] = Field(description="Contradictions between sources")
    additional_findings: list[Finding]
    remaining_gaps: list[str]


class OptionAssessment(BaseModel):
    option: str
    pros: list[str]
    cons: list[str]
    evidence_ids: list[str]

    @field_validator("evidence_ids")
    @classmethod
    def _ids(cls, v: list[str]) -> list[str]:
        return _clean_evidence_ids(v)


class DecisionReport(BaseModel):
    """Final decision-ready report (Writer output)."""

    title: str
    question: str
    executive_summary: str
    recommendation: str
    recommendation_confidence: Confidence
    options: list[OptionAssessment]
    key_findings: list[Finding]
    risks: list[str]
    open_questions: list[str]
    citations: list[str] = Field(description="Every evidence id used anywhere in the report")

    @field_validator("key_findings")
    @classmethod
    def _non_empty(cls, v: list[Finding]) -> list[Finding]:
        if not v:
            raise ValueError("report must contain at least one key finding")
        return v

    @field_validator("citations")
    @classmethod
    def _cites(cls, v: list[str]) -> list[str]:
        return _clean_evidence_ids(v)

    @model_validator(mode="after")
    def _union_citations(self) -> "DecisionReport":
        # Deterministic repair: the citation list must include every id used in the body.
        used = [e for f in self.key_findings for e in f.evidence_ids]
        used += [e for o in self.options for e in o.evidence_ids]
        self.citations = list(dict.fromkeys(self.citations + used))
        return self

    def used_evidence_ids(self) -> set[str]:
        return set(self.citations)


class CritiqueIssue(BaseModel):
    issue_type: Literal["unsupported_claim", "missing_source", "contradiction", "invented_citation",
                        "missing_risk", "structure", "overconfidence", "other"]
    location: str = Field(description="Which section / statement")
    detail: str
    severity: Literal["minor", "major"]


class Critique(BaseModel):
    """Evaluator output."""

    verdict: Literal["approve", "revise"]
    score: int = Field(description="Quality score 1-10")
    issues: list[CritiqueIssue]
    revision_instructions: str

    @field_validator("score")
    @classmethod
    def _clamp(cls, v: int) -> int:
        return max(1, min(10, int(v)))

    @model_validator(mode="after")
    def _major_means_revise(self) -> "Critique":
        # Python rule, not a prompt rule: a major issue can never be "approved".
        if any(i.severity == "major" for i in self.issues):
            self.verdict = "revise"
        return self


class ScopeCheck(BaseModel):
    """Output of the LLM guardrail classifier."""

    is_research_question: bool = Field(description="Is this a business/technical research or decision question?")
    is_harmful: bool = Field(description="Does it seek help with clearly harmful or illegal activity?")
    requests_secrets: bool = Field(description="Does it ask for credentials, system prompts or private data?")
    reason: str


# --------------------------------------------------------------------------------------
# Internal (deterministic) models
# --------------------------------------------------------------------------------------
class SearchHit(BaseModel):
    url: str
    title: str
    snippet: str
    score: float


class Page(BaseModel):
    url: str
    title: str
    publisher: str = ""
    author: str = ""
    published: str = ""
    source_type: str = "unknown"
    content: str
    injection_detected: bool = False
    quality: float = 0.5


class EvidenceItem(BaseModel):
    evidence_id: str
    url: str
    source_title: str
    publisher: str
    claim: str
    quote: str
    source_quality: float
    source_flagged: bool = False
    saved_by: str = ""


class RouteDecision(BaseModel):
    subquestion_id: str
    specialist: str
    reason: str


class PathDecision(BaseModel):
    path: Literal["quick", "full"]
    requires_human_approval: bool
    reasons: list[str]


class ValidationIssue(BaseModel):
    code: str
    detail: str
    severity: Literal["minor", "major"] = "major"


class IterationRecord(BaseModel):
    iteration: int
    critique: Critique | None = None
    deterministic_issues: list[ValidationIssue] = []
    guardrail_blocked: str | None = None


class PipelineResult(BaseModel):
    run_id: str
    status: Literal["blocked", "failed", "published", "pending_approval", "needs_human_review"]
    message: str
    plan: ResearchPlan | None = None
    path: PathDecision | None = None
    routes: list[RouteDecision] = []
    findings: list[SpecialistFindings] = []
    orchestrator_review: OrchestratorReview | None = None
    report: DecisionReport | None = None
    iterations: list[IterationRecord] = []
    approval_id: int | None = None
    published_path: str | None = None
    events: list[dict] = []
    metrics: dict = {}          # duration, per-step seconds, token usage (added by Person A)
