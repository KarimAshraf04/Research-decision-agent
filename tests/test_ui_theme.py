"""Presentation helpers (no Gradio needed)."""
from rdi.ui_theme import header_html, provider_warning, status_html, stepper_html

STEPS = {"1_plan": 6.1, "2_route": 0.0, "3_parallel_research": 80.2, "4_orchestrator": 20.4,
         "5_write_and_critique": 35.1, "6_hitl_gate": 0.1}


def test_status_card_escapes_html_and_shows_kpis():
    html = status_html("published", "<script>alert(1)</script>", "abc", ["r1"],
                       {"duration_s": 3, "usage": {"total_tokens": 1200}}, 2)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "1,200" in html and "critic rounds" in html and "rdi-card ok" in html


def test_unknown_status_does_not_crash():
    assert "weird" in status_html("weird")


def test_stepper_states():
    assert stepper_html(STEPS, "pending_approval", "full").count("rdi-step done") == 5
    assert "awaiting human" in stepper_html(STEPS, "pending_approval", "full")
    quick = {k: v for k, v in STEPS.items() if k != "4_orchestrator"}
    assert "skipped (quick path)" in stepper_html(quick, "published", "quick")
    failed = stepper_html({"1_plan": 5, "2_route": 0, "3_parallel_research": 40}, "failed", "full")
    assert "stopped here" in failed and failed.count("not reached") == 3
    assert "blocked" in stepper_html({"1_plan": 1}, "blocked", None)
    assert "running" in stepper_html(running=True)


def test_provider_warning_only_for_groq():
    assert provider_warning("gemini", "gemini") is None
    assert "Groq" in provider_warning("gemini", "groq")
    assert "rdi-bad" in header_html("x", "a", "b", "warn") and "rdi-bad" not in header_html("x", "a", "b")
