# agykit Project Context

Portable Antigravity (agy) CLI manager. Core is a single bash script `agykit`.
Includes a usage **dashboard** under `dashboard/` (Python 3 stdlib only) and
vanilla frontend assets under `web/`.

## Hard constraints (NON-NEGOTIABLE)
- **Zero pip dependencies.** Python 3 standard library ONLY (http.server, json,
  glob, argparse, webbrowser, datetime, urllib). NO fastapi/uvicorn/flask/pip.
- Bind `127.0.0.1` only. Read-only on `~/.claude` and `~/.gemini`.
- Match existing bash style for any `agykit` edits (cmd_* fns + dispatch case).

## Test / verify
- `python3 -m pytest tests -q` (new dashboard tests) must pass.
- `bash tests/run.sh` (existing bash safety suites) must stay green.

## Delege Kuralları (agy için)
Bir görev agykit (do-escalate/run) ile sana devredildiğinde:
- Verilen plan/test kontratına BİREBİR uy. Kapsam dışına çıkma.
- Testleri SİLME/DEĞİŞTİRME/ZAYIFLATMA. Şu an FAIL eden testleri GEÇİR (implementation yaz).
- Tautolojik/boş test yazma. Yeni test eklemen gerekmiyor — testler hazır.
- git komutu ÇALIŞTIRMA (commit/reset/rebase/push/stash). Değişiklikleri çalışma ağacında bırak.
- Yalnızca implementation dosyalarını oluştur/düzenle:
  `dashboard/collectors/`, `dashboard/server.py`, `dashboard/quota.py`,
  `dashboard/alerts.py`, `web/`, `agykit` (bash wiring), `README.md`.
- Terse yanıtla.
