"""Tests for the pure UI helpers (approvals screen + input validation). No Gradio needed."""
import json

import pytest

from rdi.models import DecisionReport, Finding
from rdi.services.approvals import ApprovalQueue
from rdi.services.evidence import EvidenceStore
from rdi.ui_helpers import (EMPTY_ROW, approvals_rows, clean_text, counts_markdown, format_reasons, friendly_error,
                            parse_approval_id, render_approval_report)

QUOTE = "The median infrastructure cost change after 12 months was a reduction of 18 percent."


def _payload(statement="Median costs fell 18 percent", flagged=False):
    store = EvidenceStore()
    from rdi.models import EvidenceItem
    item = EvidenceItem(evidence_id="E1", url="https://x.example/p", source_title="Study", publisher="Journal",
                        claim="cost", quote=QUOTE, source_quality=0.9, source_flagged=flagged, saved_by="run")
    store.items["E1"] = item
    report = DecisionReport(title="Adopt LMS?", question="Should we adopt?", executive_summary="Summary",
                            recommendation="Pilot first", recommendation_confidence="medium", options=[],
                            key_findings=[Finding(statement=statement, evidence_ids=["E1"], confidence="medium")],
                            risks=["lock-in"], open_questions=[], citations=[])
    return json.dumps({"report": report.model_dump(), "evidence": [item.model_dump()]})


# --- input validation ---------------------------------------------------------------------------------------
def test_clean_text():
    assert clean_text("  hello \x00 world  ", 50) == "hello  world"
    for bad in (None, "", "   \n ", "\x01\x02"):
        with pytest.raises(ValueError):
            clean_text(bad, 50, "Question")
    with pytest.raises(ValueError, match="too long"):
        clean_text("x" * 51, 50)


@pytest.mark.parametrize("value,expected", [(3, 3), (3.0, 3), ("7", 7)])
def test_parse_approval_id_ok(value, expected):
    assert parse_approval_id(value) == expected


@pytest.mark.parametrize("value", [None, "", "abc", 0, -2, float("nan")])
def test_parse_approval_id_rejects(value):
    with pytest.raises(ValueError):
        parse_approval_id(value)


def test_format_reasons_and_friendly_error():
    assert format_reasons(json.dumps(["a", "b"])) == "a • b"
    assert format_reasons("not json") == "not json"
    assert friendly_error(RuntimeError("boom\nsecond line")) == "RuntimeError: boom"
    assert friendly_error(KeyError()) == "KeyError"


# --- approvals screen -----------------------------------------------------------------------------------------
def test_rows_and_counts(tmp_path):
    q = ApprovalQueue(str(tmp_path / "ui.db"))
    assert approvals_rows(q) == EMPTY_ROW
    a = q.create("run1", "Should Delta adopt Nilo Learn?", ["High impact"], _payload())
    q.create("run2", "Second question", ["Sensitive domain"], _payload())
    q.decide(a, True, "Ahmed")
    pending = approvals_rows(q, "pending")
    assert len(pending) == 1 and pending[0][1] == "🟡 pending"
    history = approvals_rows(q, None)
    assert len(history) == 2 and {r[1] for r in history} == {"🟡 pending", "✅ approved"}
    assert "**1** pending" in counts_markdown(q) and "**1** approved" in counts_markdown(q)


def test_unreadable_db_gives_readable_row_not_exception(tmp_path):
    bad = ApprovalQueue(str(tmp_path / "ok.db"))
    bad.db_path = str(tmp_path / "missing_dir" / "x.db")      # sqlite cannot open this
    assert "cannot read queue" in approvals_rows(bad)[0][1]
    assert "unavailable" in counts_markdown(bad)


def test_review_screen_shows_everything_a_human_needs(tmp_path):
    q = ApprovalQueue(str(tmp_path / "ui.db"))
    aid = q.create("run1", "Should Delta adopt Nilo Learn?", ["High impact"], _payload())
    md = render_approval_report(aid, q)
    assert "Approval #1" in md and "High impact" in md and "✅ no issues" in md
    assert "Pilot first" in md and "Sources" in md and QUOTE in md


def test_review_screen_warns_about_invalid_content(tmp_path):
    q = ApprovalQueue(str(tmp_path / "ui.db"))
    aid = q.create("run1", "q", ["High impact"], _payload(statement="Costs fell 75 percent", flagged=True))
    md = render_approval_report(aid, q)
    assert "unsupported_number" in md and "flagged_source_only" in md and "E1" in md.split("flagged for prompt injection:**")[1]


def test_review_screen_handles_missing_and_corrupt_records(tmp_path):
    q = ApprovalQueue(str(tmp_path / "ui.db"))
    assert "No approval #5" in render_approval_report(5, q)
    aid = q.create("run1", "q", ["x"], "{this is not json")
    assert "unreadable" in render_approval_report(aid, q)
