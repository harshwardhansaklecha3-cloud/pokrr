# POKRR: notes for Claude Code

- The owner is not a developer: explain in plain words, work in small steps.
- Play chips only. Never add payments, real money, ads or tracking.
- Rules live in `docs/DECISIONS.md`. Don't invent variant rules: ask focused questions.
  Combination limits are in `engine/table.py: check_combo` (agreed 2026-11-10).
- Never expose other players' private cards or the deck in payloads, logs or debug endpoints.

## Keep GitHub up to date (owner's standing request, 2026-11-10)
The owner wants GitHub (and so the live site, which redeploys on every push to `main`) updated
every time a change is made here. After finishing a change:
1. Run the tests: `.venv\Scripts\python.exe -m pytest -q` (and the relevant `tools/*_check.py`).
2. If they pass: `git add -A`, commit with a short plain message, `git push`.
3. If they fail: fix first; never push a failing build. Tell the owner what was pushed.
Never commit `.venv/`, screenshots (`tools/ui_shots/`) or anything secret.

## Run
- Game + website: `.venv\Scripts\python.exe -m uvicorn server.app:app --port 8000`
  (website at `/`, game at `/play`).
- Checks: `tools/combo_audit.py --quick`, `tools/ui_check.py`, `tools/pace_check.py`.
- Hosting: `render.yaml` (Render free plan), own domain to come (the owner will buy a new one). Set SITE_URL in render.yaml then.
