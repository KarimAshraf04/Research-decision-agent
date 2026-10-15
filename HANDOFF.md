# HANDOFF — جزء أحمد (Person B)  ·  آخر تحديث: 12 Oct 2026

## الحالة
- [x] T1 فصل الـ corpus عن الكود + fixture قديم لتستات كريم
- [x] T2 corpus جديد (LMS للجامعة، 15 صفحة) + `EXAMPLES` + `SENSITIVE_KEYWORDS`
- [x] T3 Reliability hardening: policy (SSRF) · approvals · publisher · tools · source_quality
- [x] T4 UI + شاشة الـ approvals (`app.py` + `src/rdi/ui_helpers.py`)
- [x] T5 Tests (128 test خضرا) + `docs/person-b/GUIDE.md` (السيناريوهات 2,3,7,8,10,11 + شرح الـ bonus)

## اتجرّب إزاي
`tests/offline/scenarios.py` → 14/14 · `tests/tool_checks.py` → 9/9 · باقي الـ tests (128) اتشغلت بـ runner بديل لأن `pytest` و`gradio` و`openai-agents` مش بينزلوا في بيئتي.

## المتبقي (للـ session الجاية — على جهازك)
1. `pip install -r requirements.txt` ثم `pytest -q` (تأكد إنها خضرا بـ pytest الحقيقي).
2. `python app.py` وافتح الـ 3 تابات: تأكد إن اختيار صف في تاب 2 بيملا الـ id والتقرير (ده الجزء الوحيد المعتمد على إصدار Gradio — لو ضرب، غيّر `type="array"` أو `evt.index` في `on_select_row`).
3. Live run بـ `OPENAI_API_KEY`: Example 1, 2, 3 + السيناريوهات 7/8/10/11، وخد screenshots احتياطي.
4. لو الـ planner ما بيحطش track `risk` أو الأمثلة مش بتطلع الـ path المتوقع → عدّل الصياغة في `EXAMPLES` (مش في الـ prompts، دي بتاعة كريم).
5. ابعت لكريم: تغيير سطرين في `scenarios.py` + `CASES` في `scripts/eval_agents.py` (الأسئلة في GUIDE §7).
6. جهّز سلايداتك: code-vs-LLM، الـ guardrails، anti-hallucination، الـ bonus (GUIDE §5–6).
