# agykit Project Context

agykit v1.4.0 — Portable Antigravity (agy) CLI manager. Shell entrypoint (`agykit`) delegates `run` and `do-escalate` to a Python subprocess orchestrator (`dashboard/orchestrator.py`). Includes a usage dashboard (`dashboard/`) and vanilla frontend (`web/`).

## Architecture

```
agykit (bash)
  cmd_run          → dashboard.orchestrator run      (Python)
  cmd_do_escalate  → dashboard.orchestrator escalate (Python)
  all other cmds   → stay in bash

dashboard/orchestrator.py
  OrchestratorBase     — subprocess streaming, silence detection (120s), ping (15s)
  RunOrchestrator      — account rotation, quota detection, cache invalidation
  EscalateOrchestrator — model ladder, 3-attempt retry with backoff, verify, git rollback
```

## Hard constraints (NON-NEGOTIABLE)
- **Zero pip dependencies.** Python 3 standard library ONLY (http.server, json,
  glob, argparse, webbrowser, datetime, urllib, subprocess). NO fastapi/uvicorn/flask/pip.
- Bind `127.0.0.1` only. Read-only on `~/.claude` and `~/.gemini`.
- Match existing bash style for any `agykit` edits (cmd_* fns + dispatch case).

## Test / verify
- `python3 -m pytest tests -q` (dashboard + orchestrator tests) must pass.
- `bash tests/run.sh` (bash safety suites) must stay green.

## Key env vars (for tasks that touch orchestrator)
- `AGYKIT_SILENCE_TIMEOUT` — seconds without output before orchestrator kills agy (default: 120)
- `AGYKIT_JOB_TIMEOUT` — hard job ceiling in seconds (default: 1800)
- `AGYKIT_VERIFY` — verify command for do-escalate
- `AGYKIT_FLAGS` — extra agy flags (default: `--dangerously-skip-permissions`)

## Delegation rules (agy için)
Bir görev agykit (do-escalate/run) ile sana devredildiğinde:
- Verilen plan/test kontratına BİREBİR uy. Kapsam dışına çıkma.
- Testleri SİLME/DEĞİŞTİRME/ZAYIFLATMA. Şu an FAIL eden testleri GEÇİR (implementation yaz).
- Tautolojik/boş test yazma. Yeni test eklemen gerekmiyor — testler hazır.
- git komutu ÇALIŞTIRMA (commit/reset/rebase/push/stash). Değişiklikleri çalışma ağacında bırak.
- Yalnızca implementation dosyalarını oluştur/düzenle:
  `dashboard/`, `dashboard/orchestrator.py`, `dashboard/collectors/`, `dashboard/server.py`,
  `web/`, `agykit` (bash wiring), `README.md`.
- Terse yanıtla.
