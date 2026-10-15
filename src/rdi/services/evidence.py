"""Evidence store + claim extraction + citation validation.

Anti-fabrication design:
  * extract_candidate_claims() pulls VERBATIM sentences from the fetched page.
  * EvidenceStore.add() refuses any quote that does not literally appear in a page the
    agent actually fetched in this run -> the LLM cannot invent evidence or citations.
  * validate_report() checks every citation id in a report against this store.
"""
from __future__ import annotations

import re

from rdi.models import DecisionReport, EvidenceItem, Page, SpecialistFindings, ValidationIssue
from rdi.services.bm25 import BM25, tokenize


class FabricatedQuoteError(ValueError):
    pass


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower().strip(" .\"'")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 20]


def extract_candidate_claims(page: Page, focus: str, k: int = 6) -> list[str]:
    """Deterministic extraction: rank sentences by relevance to `focus`, prefer ones with numbers."""
    sents = [s for s in split_sentences(page.content) if not s.startswith("[REDACTED")]
    if not sents:
        return []
    bm = BM25(sents)
    scored = []
    for i, s in enumerate(bm.scores(focus)):
        bonus = 0.5 if re.search(r"\d", sents[i]) else 0.0
        scored.append((s + bonus, i))
    scored.sort(reverse=True)
    picked = sorted(i for _, i in scored[:k])
    return [sents[i] for i in picked]


class EvidenceStore:
    def __init__(self) -> None:
        self.items: dict[str, EvidenceItem] = {}
        self.pages: dict[str, Page] = {}

    @classmethod
    def from_items(cls, items: list[dict]) -> "EvidenceStore":
        """Rebuild a store from persisted evidence (used when a reviewer approves after a restart)."""
        store = cls()
        for d in items:
            item = EvidenceItem(**d)
            store.items[item.evidence_id] = item
        return store

    # pages ----------------------------------------------------------------------------
    def register_page(self, page: Page) -> None:
        self.pages[page.url] = page

    # evidence -------------------------------------------------------------------------
    def add(self, url: str, claim: str, quote: str, saved_by: str = "") -> EvidenceItem:
        page = self.pages.get(url)
        if page is None:
            raise FabricatedQuoteError(f"Page {url} was never fetched in this run; fetch it with scrape_page first.")
        if len(quote.strip()) < 15:
            raise FabricatedQuoteError("Quote too short to be meaningful evidence.")
        if _norm(quote) not in _norm(page.content):
            raise FabricatedQuoteError(
                "Quote does not appear verbatim in the fetched page. Copy an exact sentence from extract_claims output."
            )
        for existing in self.items.values():  # idempotent
            if existing.url == url and _norm(existing.quote) == _norm(quote):
                return existing
        eid = f"E{len(self.items) + 1}"
        item = EvidenceItem(evidence_id=eid, url=url, source_title=page.title, publisher=page.publisher,
                            claim=claim.strip(), quote=quote.strip(), source_quality=page.quality,
                            source_flagged=page.injection_detected, saved_by=saved_by)
        self.items[eid] = item
        return item

    def get(self, eid: str) -> EvidenceItem | None:
        if not isinstance(eid, str):
            return None
        return self.items.get(eid.strip().upper())

    def retrieve(self, query: str, k: int = 5) -> list[EvidenceItem]:
        """Bonus RAG layer: BM25 over saved evidence, re-ranked by source quality."""
        items = list(self.items.values())
        if not items:
            return []
        bm = BM25([f"{e.claim} {e.quote} {e.source_title}" for e in items])
        scored = [(s * (0.5 + e.source_quality), e) for s, e in zip(bm.scores(query), items)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for s, e in scored[:k] if s > 0] or items[:k]

    def as_table(self, ids: list[str] | None = None) -> str:
        rows = [self.items[i] for i in (ids or self.items.keys()) if i in self.items]
        lines = ["id | quality | flagged | source | claim | verbatim quote"]
        for e in rows:
            lines.append(f"{e.evidence_id} | {e.source_quality} | {'YES' if e.source_flagged else 'no'} | "
                         f"{e.publisher} ({e.url}) | {e.claim} | \"{e.quote}\"")
        return "\n".join(lines)


# ---------------------------------------------------------------------------------------
# Deterministic validators (used by output guardrails AND the evaluator loop)
# ---------------------------------------------------------------------------------------
def validate_findings(f: SpecialistFindings, store: EvidenceStore) -> list[ValidationIssue]:
    issues = []
    for i, fd in enumerate(f.findings):
        if not fd.evidence_ids:
            issues.append(ValidationIssue(code="no_evidence", detail=f"Finding {i + 1} has no evidence ids: '{fd.statement[:80]}'"))
        for eid in fd.evidence_ids:
            if store.get(eid) is None:
                issues.append(ValidationIssue(code="unknown_evidence", detail=f"Finding {i + 1} cites {eid}, which was never saved."))
    return issues


_NUM = re.compile(r"\d+(?:\.\d+)?")


def validate_report(report: DecisionReport, store: EvidenceStore) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for eid in report.citations:
        if store.get(eid) is None:
            issues.append(ValidationIssue(code="invented_citation", detail=f"{eid} is cited but does not exist in the evidence store."))
    for i, f in enumerate(report.key_findings):
        if not f.evidence_ids:
            issues.append(ValidationIssue(code="unsupported_claim", detail=f"Key finding {i + 1} has no citation: '{f.statement[:90]}'"))
            continue
        cited = [store.get(e) for e in f.evidence_ids if store.get(e)]
        if cited and all(e.source_flagged for e in cited):
            issues.append(ValidationIssue(code="flagged_source_only",
                                          detail=f"Key finding {i + 1} relies only on a source flagged for prompt injection."))
        # numbers in a finding must appear in at least one cited quote (catches invented statistics)
        quote_text = " ".join(e.quote for e in cited)
        quote_nums = set(_NUM.findall(quote_text))
        for n in _NUM.findall(f.statement):
            if cited and n not in quote_nums and len(n) > 1:
                issues.append(ValidationIssue(code="unsupported_number",
                                              detail=f"Key finding {i + 1} states '{n}' but no cited quote contains that number.",
                                              severity="major"))
                break
    for o in report.options:
        if not o.evidence_ids:
            issues.append(ValidationIssue(code="unsupported_option", detail=f"Option '{o.option}' has no evidence ids.", severity="minor"))
    if not report.risks:
        issues.append(ValidationIssue(code="missing_risks", detail="Report lists no risks.", severity="minor"))
    cited_quality = [store.get(e).source_quality for e in report.citations if store.get(e)]
    if cited_quality and report.recommendation_confidence == "high" and max(cited_quality) < 0.7:
        issues.append(ValidationIssue(code="overconfident", detail="HIGH confidence but no high-quality source is cited."))
    return issues


def drop_unsupported_findings(report: DecisionReport, store: EvidenceStore) -> tuple[DecisionReport, list[str]]:
    """Remove key findings that have no citation or state a number missing from their cited quotes.

    Used after the evaluator loop so a human reviewer never sees an unsupported statistic. Returns the
    repaired report and the removed statements. If every finding would be removed, nothing is changed.
    """
    keep, removed = [], []
    for f in report.key_findings:
        cited = [store.get(e) for e in f.evidence_ids if store.get(e)]
        quote_nums = set(_NUM.findall(" ".join(e.quote for e in cited)))
        bad_number = any(n not in quote_nums and len(n) > 1 for n in _NUM.findall(f.statement))
        (removed if not cited or bad_number else keep).append(f)
    if not removed or not keep:
        return report, []
    return report.model_copy(update={"key_findings": keep}), [f.statement for f in removed]


def relevant_terms(text: str) -> set[str]:
    return set(tokenize(text))
