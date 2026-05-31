# agykit — Claude Bağlamı

Portable Antigravity (agy) CLI yöneticisi. Çoklu hesap rotasyonu, kota-bilinçli
sıralama, model merdiveni yükseltmesi, kullanım panosu.

İşlem yapmadan önce `.claude/memory.md` oku.

## Kesin Kısıtlamalar

- **Sıfır pip bağımlılığı.** Yalnızca Python 3 stdlib (http.server, json, glob, argparse, webbrowser, datetime, urllib). FastAPI/uvicorn/flask/pip YOK.
- Yalnızca `127.0.0.1`'e bağla. `~/.claude` ve `~/.gemini` üzerinde salt okunur.
- `agykit` bash değişiklikleri için mevcut stili koru: `cmd_*` fonksiyonları + dispatch case.
- Web katmanı: vanilla JS/HTML/CSS. Framework yok.

## Test

```bash
python3 -m pytest tests -q      # dashboard testleri
bash tests/run.sh                # bash güvenlik süitleri
```

İkisi de yeşil kalmalı.

## Temel Dosyalar

- `agykit` — tek bash betiği, ana CLI
- `dashboard/server.py` — Python stdlib HTTP/SSE sunucusu
- `dashboard/collectors.py` — veri toplayıcılar (agy snapshot, statusline)
- `web/app.js` — dashboard frontend JS
- `web/style.css` — dashboard stilleri
- `CLAUDE_AGY_SYSTEM.md` — agy delege kuralları (agy için, Claude için değil)

## Delege Kuralları (agy için)

Bir görev `agykit do-escalate` veya `run` ile devredildiğinde:
- Verilen plan/test kontratına birebir uy.
- Testleri silme/değiştirme/zayıflatma.
- `git` komutu çalıştırma.
- Yalnızca implementation dosyalarını düzenle.
