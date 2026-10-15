"""Quality gate for data/corpus.json (the fictional evidence base for OUR topic).

If you rewrite the corpus for another topic, these tests tell you immediately whether the deliberate demo traps
are still there and whether the example questions in app.py still retrieve sensible pages.
"""
import asyncio
import json
import re

import pytest

from rdi import config
from rdi.services.evidence import extract_candidate_claims
from rdi.services.injection import detect_injection, sanitize_untrusted
from rdi.services.search_backend import LocalCorpusBackend, ToolFailure, fetch_with_retry, load_corpus
from rdi.services.source_quality import TYPE_SCORES, score_source

pytestmark = pytest.mark.usefixtures("real_corpus")


@pytest.fixture
def pages():
    return load_corpus(config.CORPUS_PATH)


def _by_type(pages, t):
    return [p for p in pages if p["source_type"] == t]


# --- shape ------------------------------------------------------------------------------------
def test_size_and_uniqueness(pages):
    assert 12 <= len(pages) <= 16
    assert len({p["url"] for p in pages}) == len(pages)
    assert all(p["url"].startswith("https://") and ".example" in p["url"] for p in pages), "keep URLs fictional (.example)"


def test_fields_and_types_are_valid(pages):
    for p in pages:
        assert p["source_type"] in TYPE_SCORES, p["url"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["published"]), p["url"]
        assert len(p["content"]) > 60
        assert p.get("simulate_failure") in (None, "always", "once")


def test_mix_of_source_qualities(pages):
    types = {p["source_type"] for p in pages}
    assert {"peer_reviewed", "official_docs", "industry_report", "vendor_marketing"} <= types
    assert types & {"forum", "blog"}, "need at least one low-quality source"


# --- deliberate traps ---------------------------------------------------------------------------
def test_exactly_one_injected_page_and_it_is_caught(pages):
    injected = [p for p in pages if detect_injection(p["content"]).is_injection]
    assert len(injected) == 1
    clean, res = sanitize_untrusted(injected[0]["content"])
    assert {"override", "system_spoof"} <= set(res.categories)
    assert "ignore all previous" not in clean.lower() and "REDACTED" in clean
    assert score_source(injected[0]["source_type"], injected[0]["published"], injected[0]["author"], True) <= 0.10


def test_no_other_page_trips_the_injection_detector(pages):
    for p in pages:
        if "edtech-roundup" not in p["url"]:
            assert not detect_injection(p["content"]).is_injection, p["url"]


def test_failure_simulation_pages(pages):
    assert sum(p.get("simulate_failure") == "always" for p in pages) == 1
    assert sum(p.get("simulate_failure") == "once" for p in pages) == 1


def test_vendor_marketing_contradicts_peer_reviewed(pages):
    vendor = _by_type(pages, "vendor_marketing")[0]["content"]
    study = _by_type(pages, "peer_reviewed")[0]["content"]
    assert "55 percent" in vendor and "14 percent" in study    # vendor "up to 55%" vs measured median 14%
    assert score_source("peer_reviewed", "2026-02-10", "Dr X", False) > score_source("vendor_marketing", "2026-05-12", "M", False)


def test_dead_page_fails_and_flaky_page_recovers():
    backend = LocalCorpusBackend()
    dead = next(p for p in backend.pages if p.get("simulate_failure") == "always")["url"]
    flaky = next(p for p in backend.pages if p.get("simulate_failure") == "once")["url"]
    with pytest.raises(ToolFailure):
        asyncio.run(fetch_with_retry(dead, retries=1))
    retries = []
    page = asyncio.run(fetch_with_retry(flaky, on_retry=lambda a, m: retries.append(m)))
    assert page.title and len(retries) == 1


def test_every_extracted_claim_is_verbatim(pages):
    backend = LocalCorpusBackend()
    for p in pages:
        if p.get("simulate_failure") == "always":
            continue  # the dead link can never be fetched - that is the point of the page
        page = asyncio.run(backend.fetch(p["url"], attempt=1))
        for claim in extract_candidate_claims(page, "cost price students"):
            assert claim in page.content


# --- the example questions of app.py retrieve the right pages -----------------------------------------
RETRIEVAL = [
    ("Nilo Learn migration cost study universities", "lms-migration-study-2026"),
    ("Nilo Learn pricing per student implementation fees", "lms-pricing-universities"),
    ("Nilo Learn outage uptime exam week", "nilo-exam-week-outage"),
    ("student data residency compliance cloud LMS", "student-data-residency"),
    ("vendor lock-in export fee Nilo Learn contract", "lms-lock-in-review"),
    ("Atlas Open pilot hosting plan pricing", "atlas-open"),
    ("peak concurrent users benchmark exam week Nilo Learn", "lms-exam-week-load-benchmark"),
    ("LMS security student grade exports", "lms-security-findings"),
]


@pytest.mark.parametrize("query,expected", RETRIEVAL)
def test_search_finds_expected_page(query, expected):
    hits = asyncio.run(LocalCorpusBackend().search(query, 4))
    assert any(expected in h.url for h in hits[:3]), [h.url for h in hits]


def test_quick_path_example_hits_the_flaky_benchmark_first():
    hits = asyncio.run(LocalCorpusBackend().search("exam-week benchmark peak concurrent-user capacity Nilo Learn", 3))
    assert "lms-exam-week-load-benchmark" in hits[0].url


# --- loader failure modes (reliability) -----------------------------------------------------------------
def test_loader_rejects_bad_files(tmp_path):
    bad_json = tmp_path / "a.json"; bad_json.write_text("{ not json")
    no_pages = tmp_path / "b.json"; no_pages.write_text(json.dumps({"pages": []}))
    missing = tmp_path / "c.json"; missing.write_text(json.dumps({"pages": [{"url": "https://x.example/1", "title": "t"}]}))
    dup_page = {"url": "https://x.example/1", "title": "t", "publisher": "p", "content": "some content here"}
    dup = tmp_path / "d.json"; dup.write_text(json.dumps({"pages": [dup_page, dup_page]}))
    for f in (bad_json, no_pages, missing, dup, tmp_path / "nope.json"):
        with pytest.raises(ToolFailure):
            load_corpus(f)
