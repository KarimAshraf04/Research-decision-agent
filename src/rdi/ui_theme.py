"""Visual layer for the Gradio UI: CSS + small HTML builders (pure functions, no Gradio import -> unit-testable).

app.py wires these into components; nothing here changes behaviour, only presentation.
"""
from __future__ import annotations

from html import escape

# (step key recorded by runtime.step(), label, orchestration pattern shown under it)
PIPELINE_STEPS = [
    ("1_plan", "Plan", "Prompt chaining"),
    ("2_route", "Route", "Code routing"),
    ("3_parallel_research", "Research", "Parallel"),
    ("4_orchestrator", "Orchestrate", "LLM delegation"),
    ("5_write_and_critique", "Write ⇄ Critique", "Evaluator loop"),
    ("6_hitl_gate", "Human gate", "HITL"),
]

STATUS_STYLE = {
    # status: (css class, icon, title)
    "published": ("ok", "✓", "Published"),
    "pending_approval": ("wait", "⏸", "Waiting for human approval"),
    "needs_human_review": ("warn", "!", "Escalated to human review"),
    "blocked": ("block", "⛔", "Blocked by guardrail"),
    "failed": ("err", "✕", "Run failed"),
    "running": ("run", "◌", "Research in progress"),
    "input": ("warn", "!", "Check your input"),
}

CSS = """
:root { --rdi-radius: 14px; }
.gradio-container { max-width: 1280px !important; margin: 0 auto !important; }
#rdi-header { border-radius: var(--rdi-radius); padding: 22px 26px; margin-bottom: 6px;
  background: linear-gradient(135deg, #312e81 0%, #4338ca 45%, #0f766e 100%); color: #fff; }
#rdi-header h1 { margin: 0 0 4px 0; font-size: 1.65rem; font-weight: 700; letter-spacing: -0.01em; color: #fff; }
#rdi-header p { margin: 0; opacity: .88; font-size: .95rem; color: #fff; }
.rdi-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; align-items: center; }
.rdi-chip { background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.22); color: #fff;
  border-radius: 999px; padding: 3px 11px; font-size: .78rem; white-space: nowrap; }
.rdi-arrow { opacity: .6; font-size: .8rem; color: #fff; }
.rdi-provider { margin-top: 12px; font-size: .8rem; opacity: .95; color: #fff; }
.rdi-provider code { background: rgba(0,0,0,.25); color: #fff; padding: 1px 6px; border-radius: 6px; }
.rdi-provider .rdi-bad { background: #fbbf24; color: #3b2600; padding: 1px 8px; border-radius: 6px; font-weight: 600; }

.rdi-card { border-radius: var(--rdi-radius); padding: 16px 18px; border: 1px solid; margin: 4px 0; }
.rdi-card .rdi-title { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.05rem; }
.rdi-card .rdi-icon { width: 26px; height: 26px; border-radius: 50%; display: inline-flex; align-items: center;
  justify-content: center; font-size: .85rem; color: #fff; flex: none; }
.rdi-card .rdi-run { font-family: ui-monospace, monospace; font-size: .78rem; opacity: .7; margin-left: auto; }
.rdi-card .rdi-msg { margin: 8px 0 0 36px; font-size: .92rem; line-height: 1.5; white-space: pre-wrap; }
.rdi-card ul { margin: 8px 0 0 36px; padding-left: 16px; font-size: .85rem; opacity: .9; }
.rdi-card.ok    { background: rgba(16,185,129,.09); border-color: rgba(16,185,129,.45); }
.rdi-card.ok .rdi-icon { background: #10b981; }
.rdi-card.wait  { background: rgba(245,158,11,.10); border-color: rgba(245,158,11,.5); }
.rdi-card.wait .rdi-icon { background: #f59e0b; }
.rdi-card.warn  { background: rgba(249,115,22,.10); border-color: rgba(249,115,22,.5); }
.rdi-card.warn .rdi-icon { background: #f97316; }
.rdi-card.block { background: rgba(100,116,139,.12); border-color: rgba(100,116,139,.5); }
.rdi-card.block .rdi-icon { background: #475569; }
.rdi-card.err   { background: rgba(239,68,68,.09); border-color: rgba(239,68,68,.5); }
.rdi-card.err .rdi-icon { background: #ef4444; }
.rdi-card.run   { background: rgba(99,102,241,.09); border-color: rgba(99,102,241,.45); }
.rdi-card.run .rdi-icon { background: #6366f1; animation: rdi-pulse 1.4s ease-in-out infinite; }
.rdi-card.idle  { background: transparent; border-style: dashed; border-color: rgba(148,163,184,.45); opacity: .8; }
.rdi-card.idle .rdi-icon { background: #94a3b8; }

.rdi-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; margin: 12px 0 0 36px; }
.rdi-kpi { border-radius: 10px; padding: 8px 10px; background: rgba(148,163,184,.10); }
.rdi-kpi b { display: block; font-size: 1.05rem; }
.rdi-kpi span { font-size: .72rem; opacity: .7; text-transform: uppercase; letter-spacing: .04em; }

.rdi-steps { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin: 8px 0 4px; }
.rdi-step { border-radius: 12px; padding: 10px 10px 9px; border: 1px solid rgba(148,163,184,.35); position: relative; }
.rdi-step .n { font-size: .68rem; opacity: .6; font-weight: 600; }
.rdi-step .l { font-weight: 700; font-size: .9rem; margin-top: 2px; }
.rdi-step .p { font-size: .7rem; opacity: .7; }
.rdi-step .s { font-size: .72rem; margin-top: 6px; font-weight: 600; }
.rdi-step.done    { border-color: rgba(16,185,129,.6); background: rgba(16,185,129,.08); }
.rdi-step.done .s { color: #059669; }
.rdi-step.wait    { border-color: rgba(245,158,11,.6); background: rgba(245,158,11,.09); }
.rdi-step.wait .s { color: #d97706; }
.rdi-step.fail    { border-color: rgba(239,68,68,.6); background: rgba(239,68,68,.08); }
.rdi-step.fail .s { color: #dc2626; }
.rdi-step.block   { border-color: rgba(100,116,139,.7); background: rgba(100,116,139,.12); }
.rdi-step.skip    { opacity: .55; border-style: dashed; }
.rdi-step.todo    { opacity: .5; }
.rdi-step.active  { border-color: rgba(99,102,241,.7); background: rgba(99,102,241,.10); animation: rdi-pulse 1.4s ease-in-out infinite; }
@keyframes rdi-pulse { 0%,100% { opacity: 1 } 50% { opacity: .55 } }
@media (max-width: 820px) { .rdi-steps { grid-template-columns: repeat(3, 1fr); } }

#rdi-run-btn { min-height: 52px; font-size: 1.02rem; font-weight: 700; }
.rdi-section-note { font-size: .85rem; opacity: .75; margin: 2px 0 6px; }
footer { display: none !important; }
"""


def header_html(provider_label: str, model_smart: str, model_fast: str, warning: str | None = None) -> str:
    chips = []
    for i, (_, label, pattern) in enumerate(PIPELINE_STEPS):
        if i:
            chips.append('<span class="rdi-arrow">→</span>')
        chips.append(f'<span class="rdi-chip" title="{escape(pattern)}">{escape(label)}</span>')
    warn = f' <span class="rdi-bad">⚠ {escape(warning)}</span>' if warning else ""
    return (
        '<div id="rdi-header">'
        "<h1>🔎 Research &amp; Decision Intelligence Agent</h1>"
        "<p>Turns a business or technical decision question into a cited, critic-reviewed, decision-ready report — "
        "with guardrails and a human in the loop.</p>"
        f'<div class="rdi-chips">{"".join(chips)}</div>'
        f'<div class="rdi-provider">LLM provider: <b>{escape(provider_label)}</b> · smart '
        f"<code>{escape(model_smart)}</code> · fast <code>{escape(model_fast)}</code>{warn}</div>"
        "</div>"
    )


def provider_warning(provider_smart: str, provider_fast: str) -> str | None:
    if "groq" in (provider_smart, provider_fast):
        return "Groq cannot combine tools with structured output — specialists will fail. Use gemini in .env."
    return None


def _kpis(metrics: dict | None, iterations: int | None) -> str:
    if not metrics:
        return ""
    usage = metrics.get("usage") or {}
    items = [
        (f'{metrics.get("duration_s", "–")} s', "duration"),
        (f'{usage.get("total_tokens", 0):,}', "tokens"),
        (str(metrics.get("pages_read", 0)), "pages read"),
        (str(metrics.get("evidence_items", 0)), "evidence items"),
        (str(metrics.get("delegations", 0)), "delegations"),
    ]
    if iterations is not None:
        items.append((str(iterations), "critic rounds"))
    cells = "".join(f'<div class="rdi-kpi"><b>{escape(v)}</b><span>{escape(k)}</span></div>' for v, k in items)
    return f'<div class="rdi-kpis">{cells}</div>'


def status_html(status: str, message: str = "", run_id: str | None = None, reasons: list[str] | None = None,
                metrics: dict | None = None, iterations: int | None = None, extra: str | None = None) -> str:
    css, icon, title = STATUS_STYLE.get(status, ("block", "•", status))
    run = f'<span class="rdi-run">run {escape(run_id)}</span>' if run_id else ""
    msg = f'<div class="rdi-msg">{escape(message)}</div>' if message else ""
    lis = "".join(f"<li>{escape(r)}</li>" for r in (reasons or []))
    reasons_html = f"<ul>{lis}</ul>" if lis else ""
    extra_html = f'<div class="rdi-msg"><b>{escape(extra)}</b></div>' if extra else ""
    return (f'<div class="rdi-card {css}"><div class="rdi-title"><span class="rdi-icon">{icon}</span>'
            f"{escape(title)}{run}</div>{msg}{extra_html}{reasons_html}{_kpis(metrics, iterations)}</div>")


def idle_html() -> str:
    return ('<div class="rdi-card idle"><div class="rdi-title"><span class="rdi-icon">i</span>Ready</div>'
            '<div class="rdi-msg">Type a decision question or pick an example, then press Run research. '
            "On the free tier a full run takes a few minutes.</div></div>")


def running_html(question: str) -> str:
    return status_html("running", f"“{question[:220]}”\n\nPlanning, researching and reviewing — this can take a few "
                                  "minutes on a free-tier model. The steps below light up when the run finishes.")


def stepper_html(steps_s: dict | None = None, status: str | None = None, path: str | None = None,
                 running: bool = False) -> str:
    steps_s = steps_s or {}
    executed = [k for k, _, _ in PIPELINE_STEPS if k in steps_s]
    last = executed[-1] if executed else None
    cells = []
    for i, (key, label, pattern) in enumerate(PIPELINE_STEPS, start=1):
        if running:
            cls, state = ("active", "running…") if i == 1 else ("todo", "queued")
        elif key in steps_s:
            secs = f"{steps_s[key]:.1f}s" if isinstance(steps_s[key], (int, float)) else ""
            cls, state = "done", f"✓ {secs}"
            if key == last and status == "failed":
                cls, state = "fail", "✕ stopped here"
            elif key == last and status == "blocked":
                cls, state = "block", "⛔ blocked"
            elif key == "6_hitl_gate" and status in ("pending_approval", "needs_human_review"):
                cls, state = "wait", "⏸ awaiting human"
        elif key == "4_orchestrator" and path == "quick" and "5_write_and_critique" in steps_s:
            cls, state = "skip", "skipped (quick path)"
        else:
            cls, state = "todo", "not reached" if status else "—"
        cells.append(f'<div class="rdi-step {cls}"><div class="n">STEP {i}</div><div class="l">{escape(label)}</div>'
                     f'<div class="p">{escape(pattern)}</div><div class="s">{escape(state)}</div></div>')
    return f'<div class="rdi-steps">{"".join(cells)}</div>'
