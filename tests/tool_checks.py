"""Offline checks of the REAL function tools (tools.py) against the REAL corpus (data/corpus.json).

Runs with the FAKE openai-agents SDK (same trick as tests/offline/scenarios.py), so it needs no API key and
works whether or not the real SDK is installed. Covers demo scenarios owned by Person B:
  2 multi-step tools · 7/8 blocked tool · 10 failure + recovery · plus argument validation.

    python tests/tool_checks.py          # human readable
    python tests/tool_checks.py --json   # used by tests/test_tools_offline.py
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import tempfile
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests/offline/fake_sdk"), str(ROOT / "src")]

from agents import RunContextWrapper  # noqa: E402  (FAKE sdk)

from rdi import config  # noqa: E402

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="rdi_toolchecks_"))
config.OUTPUT_DIR, config.APPROVAL_DB = _TMP, str(_TMP / "approvals.db")
config.CORPUS_PATH = ROOT / "data" / "corpus.json"

from rdi import tools as T  # noqa: E402
from rdi.context import ResearchContext  # noqa: E402
from rdi.models import DecisionReport, Finding  # noqa: E402

STUDY = "https://journal.edtech-evidence.example/lms-migration-study-2026"
INJECTED = "https://edtech-roundup.example/nilo-vs-legacy-honest-comparison"
DEAD = "https://archive.old-edu-news.example/2019/nilo-learn-campus-edition-launch"
FLAKY = "https://edubench-labs.example/2026/lms-exam-week-load-benchmark"
VENDOR = "https://nilolearn.example/blog/why-universities-choose-nilo-learn"


def new_ctx(**kw):
    ctx = ResearchContext(**kw)
    return ctx, RunContextWrapper(ctx)


async def call(tool, w, **kw):
    return json.loads(await tool(w, **kw))


def kinds(ctx, kind):
    return [e["message"] for e in ctx.events if e["kind"] == kind]


async def save_first_quote(w, url, focus):
    page = await call(T.scrape_page, w, url=url)
    assert page["ok"], page
    claims = await call(T.extract_claims, w, url=url, focus=focus)
    assert claims["ok"] and claims["candidate_quotes"], claims
    return await call(T.save_evidence, w, url=url, claim="paraphrase of the quote", quote=claims["candidate_quotes"][0])


# ----------------------------------------------------------------------------------------------- checks
async def c_sequential_tools():  # scenario 2
    ctx, w = new_ctx()
    hits = await call(T.search_web, w, query="Nilo Learn migration cost study universities", max_results=4)
    assert hits["ok"] and hits["results"][0]["url"] == STUDY, hits["results"][:2]
    ev = await save_first_quote(w, STUDY, "median cost change after migration")
    assert ev["ok"] and ev["evidence_id"] == "E1" and ev["source_quality"] >= 0.8 and not ev["source_flagged"]
    cmp_ = await call(T.compare_sources, w, evidence_ids=["E1", "E1"])  # duplicates collapse -> not enough
    assert not cmp_["ok"]
    seq = [e["message"].split("(")[0] for e in ctx.events if e["kind"] == "tool"]
    assert seq[:3] == ["search_web", "scrape_page", "extract_claims"], seq
    return "search -> scrape -> extract -> save chained; E1 quality %.2f" % ev["source_quality"]


async def c_blocked_tool():  # scenario 8
    ctx, w = new_ctx()
    bad = ["http://169.254.169.254/latest", "file:///etc/passwd", "http://2130706433/", "http://0x7f000001/",
           "http://LOCALHOST./admin", "http://10.0.0.5/", "http://100.64.0.1/", "http://intranet/", ""]
    for u in bad:
        r = await call(T.scrape_page, w, url=u)
        assert r["ok"] is False and r.get("blocked") is True, (u, r)
    assert len(kinds(ctx, "blocked")) == len(bad) and not ctx.evidence.pages
    return f"{len(bad)} dangerous URLs blocked by Python policy; nothing fetched"


async def c_injection_page():  # scenario 7 (tool-result injection) 
    ctx, w = new_ctx()
    page = await call(T.scrape_page, w, url=INJECTED)
    assert page["ok"] and page["injection_detected"] is True and page["quality"] <= 0.10, page
    low = page["content"].lower()
    assert "ignore all previous" not in low and "system note" not in low and "redacted" in low
    assert page["warning"] and kinds(ctx, "injection")
    claims = await call(T.extract_claims, w, url=INJECTED, focus="cost of legacy servers")
    ev = await call(T.save_evidence, w, url=INJECTED, claim="blog says legacy costs more", quote=claims["candidate_quotes"][0])
    assert ev["ok"] and ev["source_flagged"] is True and ev["source_quality"] <= 0.10
    return "injected blog redacted, flagged, quality capped at 0.10; its evidence stays flagged"


async def c_fabricated_quote_rejected():
    ctx, w = new_ctx()
    await call(T.scrape_page, w, url=VENDOR)
    r = await call(T.save_evidence, w, url=VENDOR, claim="vendor claims 90 percent savings",
                   quote="Nilo Learn customers cut total LMS costs by 90 percent in a week.")
    assert r["ok"] is False and r.get("rejected") is True and not ctx.evidence.items
    r2 = await call(T.save_evidence, w, url="https://never-fetched.example/x", claim="invented source claim",
                    quote="This sentence was never on any fetched page at all.")
    assert r2["ok"] is False and r2.get("rejected") is True
    return "fabricated quote and never-fetched URL both rejected; evidence store stays empty"


async def c_dead_page_recovery():  # scenario 10
    ctx, w = new_ctx()
    r = await call(T.scrape_page, w, url=DEAD)
    assert r["ok"] is False and "gave up" in r["error"] and "another" in r["error"].lower()
    assert len(kinds(ctx, "tool_retry")) == config.FETCH_RETRIES + 1 and kinds(ctx, "tool_failure")
    ok = await call(T.scrape_page, w, url=STUDY)   # the run carries on with a different source
    assert ok["ok"]
    return f"dead link: {config.FETCH_RETRIES + 1} attempts with backoff, clean error, next source works"


async def c_flaky_page_recovery():  # scenario 10
    ctx, w = new_ctx()
    r = await call(T.scrape_page, w, url=FLAKY)
    assert r["ok"] and r["source_type"] == "industry_report" and len(kinds(ctx, "tool_retry")) == 1
    return "flaky page failed once, retry succeeded; 1 tool_retry event"


async def c_search_outage_recovery():  # scenario 10
    ctx, w = new_ctx(fault_search_outage=True)
    first = await call(T.search_web, w, query="Atlas Open hosting plan pricing", max_results=3)
    assert first["ok"] is False and "503" in first["error"] and kinds(ctx, "tool_failure")
    second = await call(T.search_web, w, query="Atlas Open hosting plan pricing", max_results=3)
    assert second["ok"] and second["results"]
    return "first search = simulated 503, retry works"


async def c_argument_validation():
    ctx, w = new_ctx()
    assert not (await call(T.search_web, w, query="x", max_results=3))["ok"]
    assert not (await call(T.search_web, w, query="y" * 500, max_results=3))["ok"]
    odd = await call(T.search_web, w, query="Atlas Open pricing", max_results="lots")   # malformed arg -> default
    assert odd["ok"], odd
    assert not (await call(T.extract_claims, w, url=STUDY, focus="cost"))["ok"]           # not scraped yet
    await call(T.scrape_page, w, url=STUDY)
    assert not (await call(T.extract_claims, w, url=STUDY, focus="   "))["ok"]
    assert not (await call(T.save_evidence, w, url=STUDY, claim="", quote="x" * 40))["ok"]
    assert not (await call(T.save_evidence, w, url=STUDY, claim="a claim", quote="x" * 5000))["ok"]
    assert not (await call(T.compare_sources, w, evidence_ids=["E1"]))["ok"]
    assert not (await call(T.compare_sources, w, evidence_ids="E1,E2"))["ok"]            # not a list
    assert not (await call(T.check_claim_support, w, statement="", evidence_ids=["E1"]))["ok"]
    r = await call(T.check_claim_support, w, statement="Costs fell 99 percent", evidence_ids=["E404", 7])
    assert r["ok"] and r["supported"] is False and r["unknown_ids"] == ["E404"]
    assert not (await call(T.retrieve_evidence, w, query=" "))["ok"]
    assert not (await call(T.publish_report, w))["ok"]                                  # no report yet
    return "13 malformed calls answered with clean errors, none raised"


async def c_publish_protected():  # scenario 8/11
    ctx, w = new_ctx(question="Should we adopt?")
    ev = await save_first_quote(w, STUDY, "median cost change after migration")
    ctx.report = DecisionReport(title="T", question="Q", executive_summary="S", recommendation="R",
                                recommendation_confidence="medium", options=[],
                                key_findings=[Finding(statement="The study reports a cost change", evidence_ids=["E1"], confidence="medium")],
                                risks=["lock-in"], open_questions=[], citations=[])
    # numbers in the statement would be checked; this one has none -> only approval blocks it
    ctx.requires_approval = True
    r = await call(T.publish_report, w)
    assert r["ok"] is False and r.get("blocked") and "approval" in r["error"].lower() and not ctx.published_path
    ctx.requires_approval = False
    r2 = await call(T.publish_report, w)
    assert r2["ok"] and pathlib.Path(r2["published_path"]).exists()
    return "publish blocked while approval missing; allowed only when Python rules pass"


CHECKS = [c_sequential_tools, c_blocked_tool, c_injection_page, c_fabricated_quote_rejected, c_dead_page_recovery,
          c_flaky_page_recovery, c_search_outage_recovery, c_argument_validation, c_publish_protected]


async def main():
    out = []
    for fn in CHECKS:
        name = fn.__name__[2:]
        try:
            out.append({"scenario": name, "passed": True, "detail": await fn(), "trace": ""})
        except Exception as e:  # noqa: BLE001
            out.append({"scenario": name, "passed": False, "detail": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()})
    return out


if __name__ == "__main__":
    res = asyncio.run(main())
    if "--json" in sys.argv:
        print(json.dumps(res))
    else:
        w = max(len(r["scenario"]) for r in res)
        for r in res:
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['scenario']:<{w}}  {r['detail']}")
            if not r["passed"]:
                print(r["trace"])
        print(f"\n{sum(r['passed'] for r in res)}/{len(res)} checks passed")
    sys.exit(0 if all(r["passed"] for r in res) else 1)
