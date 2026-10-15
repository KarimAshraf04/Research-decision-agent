"""Reliability / safety tests for the deterministic layer: URL policy (SSRF), approval queue, publisher, scoring."""
import json
import sqlite3
import threading

import pytest

from rdi.models import DecisionReport, Finding
from rdi.services.approvals import ApprovalQueue
from rdi.services.evidence import EvidenceStore
from rdi.services.policy import ActionBlocked, check_url_allowed, is_sensitive
from rdi.services.publisher import publish_report
from rdi.services.search_backend import LocalCorpusBackend
from rdi.services.source_quality import score_source

STUDY = "https://journal.cloudops-research.example/stratus-migration-study-2026"


# --- tool-level guardrail: SSRF bypass attempts ------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "http://2130706433/",              # 127.0.0.1 as one decimal number
    "http://0x7f000001/",              # hex
    "http://0177.0.0.1/",              # octal
    "http://127.1/",                   # short form
    "http://[::ffff:127.0.0.1]/",      # IPv4-mapped IPv6
    "http://[::1]/", "http://[fd00::1]/",
    "http://LOCALHOST./", "http://foo.localhost/", "http://service.internal/",
    "http://100.64.0.1/",              # carrier-grade NAT
    "http://192.168.1.1/", "http://172.16.0.9/",
    "http://example.com@127.0.0.1/",   # userinfo trick
    "http://intranet/",                # single-label host
    "https://exa mple.com/", "http://a.example/\nHost: evil", "https://example.com:99999/",
    "ftp://example.com/x", "javascript:alert(1)", "file:///etc/passwd", "", "   ", "http://",
    "https://example.com/" + "a" * 3000,
])
def test_dangerous_or_malformed_urls_are_blocked(url):
    with pytest.raises(ActionBlocked):
        check_url_allowed(url)


@pytest.mark.parametrize("url", ["https://journal.edtech-evidence.example/x", "HTTP://Example.com/ok",
                                 "https://example.com:8443/a?b=c", "http://8.8.8.8/"])
def test_normal_public_urls_are_allowed(url):
    check_url_allowed(url)


def test_non_string_url_is_blocked_not_crashing():
    with pytest.raises(ActionBlocked):
        check_url_allowed(None)  # type: ignore[arg-type]


def test_sensitive_keywords_for_university_topic():
    assert is_sensitive("Should we move student records to a vendor cloud?")
    assert is_sensitive("Plan staff cuts after the LMS migration")
    assert not is_sensitive("Which hosting plan is cheapest for a pilot?")


# --- approval queue ----------------------------------------------------------------------------------------
def _queue(tmp_path):
    return ApprovalQueue(str(tmp_path / "q.db"))


def test_decide_requires_named_reviewer_and_sane_lengths(tmp_path):
    q = _queue(tmp_path)
    aid = q.create("r1", "q", ["high impact"], "{}")
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            q.decide(aid, True, bad)
    with pytest.raises(ValueError):
        q.decide(aid, True, "x" * 200)
    with pytest.raises(ValueError):
        q.decide(aid, True, "Ahmed", note="n" * 5000)
    assert q.get(aid)["status"] == "pending"          # nothing above changed the record


def test_unknown_approval_and_empty_run_id(tmp_path):
    q = _queue(tmp_path)
    with pytest.raises(ValueError):
        q.decide(999, True, "Ahmed")
    with pytest.raises(ValueError):
        q.create("  ", "q", [], "{}")


def test_double_decision_is_atomic_under_concurrency(tmp_path):
    q = _queue(tmp_path)
    aid = q.create("r1", "q", ["x"], "{}")
    outcomes = []

    def worker(approve):
        try:
            q.decide(aid, approve, f"reviewer-{approve}")
            outcomes.append("won")
        except ValueError:
            outcomes.append("lost")

    threads = [threading.Thread(target=worker, args=(i % 2 == 0,)) for i in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert outcomes.count("won") == 1 and outcomes.count("lost") == 7
    assert q.get(aid)["status"] in {"approved", "rejected"}


def test_counts_history_and_timestamps(tmp_path):
    q = _queue(tmp_path)
    a, b, c = (q.create(f"r{i}", "q", ["x"], "{}") for i in range(3))
    q.decide(a, True, "Ahmed"); q.decide(b, False, "Karim", "too risky")
    assert q.counts() == {"pending": 1, "approved": 1, "rejected": 1}
    assert [r["id"] for r in q.list("pending")] == [c]
    assert len(q.list(None)) == 3
    rec = q.get(b)
    assert rec["status"] == "rejected" and rec["note"] == "too risky" and rec["decided_at"] and rec["created_at"]


def test_latest_decision_wins_for_a_run(tmp_path):
    q = _queue(tmp_path)
    first = q.create("run", "q", ["x"], "{}")
    q.decide(first, True, "Ahmed")
    second = q.create("run", "q", ["x"], "{}")          # a re-run created a newer pending record
    assert q.latest_for_run("run")["id"] == second and q.latest_for_run("run")["status"] == "pending"


def test_connections_are_closed(tmp_path):
    q = _queue(tmp_path)
    with q._conn() as c:
        c.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        c.execute("SELECT 1")                            # closed after the with-block (no leaked handles)


def test_failed_write_rolls_back(tmp_path):
    q = _queue(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        with q._conn() as c:
            c.execute("INSERT INTO approvals(run_id, question, reasons, report_json, created_at) VALUES (NULL,'q','[]','{}','t')")
    assert q.list(None) == []


# --- publisher ------------------------------------------------------------------------------------------------
def _store_and_report():
    import asyncio
    page = asyncio.run(LocalCorpusBackend(config_fixture()).fetch(STUDY, 0))
    page.quality = 0.9
    store = EvidenceStore(); store.register_page(page)
    store.add(STUDY, "cost", "The median infrastructure cost change after 12 months was a reduction of 18 percent.")
    report = DecisionReport(title="T", question="Q", executive_summary="S", recommendation="R",
                            recommendation_confidence="medium", options=[],
                            key_findings=[Finding(statement="Median costs fell 18 percent", evidence_ids=["E1"], confidence="medium")],
                            risks=["lock-in"], open_questions=[], citations=[])
    return store, report


def config_fixture():
    import pathlib
    return pathlib.Path(__file__).parent / "fixtures" / "corpus_logistics.json"


def test_publish_filename_cannot_escape_output_dir(tmp_path):
    from rdi import config
    store, report = _store_and_report()
    out = publish_report("../../evil/../x", report, store, requires_approval=False)
    path = __import__("pathlib").Path(out)
    assert path.parent == config.OUTPUT_DIR and ".." not in path.name and path.exists()


def test_publish_leaves_no_temp_file_and_overwrites_cleanly(tmp_path):
    from rdi import config
    store, report = _store_and_report()
    publish_report("run9", report, store, requires_approval=False)
    publish_report("run9", report, store, requires_approval=False)
    assert sorted(p.name for p in config.OUTPUT_DIR.iterdir()) == ["report_run9.md"]


def test_rejected_approval_never_publishes(tmp_path):
    store, report = _store_and_report()
    q = ApprovalQueue()
    aid = q.create("runR", "q", ["high impact"], json.dumps({}))
    q.decide(aid, False, "Ahmed", "no")
    with pytest.raises(ActionBlocked):
        publish_report("runR", report, store, requires_approval=True, queue=q)


# --- source quality ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("published", ["", "not-a-date", None])
def test_source_quality_survives_bad_dates(published):
    s = score_source("news", published, "Someone", False)
    assert 0.0 <= s <= 1.0


def test_source_quality_ordering():
    peer = score_source("peer_reviewed", "2026-03-01", "Dr A", False)
    vendor = score_source("vendor_marketing", "2026-03-01", "Marketing", False)
    forum = score_source("forum", "2026-03-01", "user1", False)
    old = score_source("peer_reviewed", "2019-03-01", "Dr A", False)
    assert peer > vendor > forum and old < peer
