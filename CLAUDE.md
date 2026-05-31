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

## CLI Referansı

### Hesap Yönetimi
```bash
agykit whoami                  # aktif hesap e-postası
agykit account-list            # kayıtlı snapshot'lar
agykit switch <email>          # hesap değiştir (keyring + snapshot)
agykit account-save            # mevcut oturumu kaydet
agykit account-add             # yeni hesap: agy başlat → giriş → kaydet
agykit account-remove <email>  # snapshot sil (aktif hesap silinemez)
```

### Görev Delegasyonu
```bash
agykit run "prompt"            # basit sorgu/açıklama — kota-bilinçli rotasyon
agykit do-escalate "prompt"    # kod görevi — verify fail → model ladder
```

**`run` ne zaman:** Açıklama, araştırma, tek adımlı iş. Verify gerekmez.  
**`do-escalate` ne zaman:** Kod değişikliği + `AGYKIT_VERIFY` tanımlı (test/lint). Başarısız olursa sıradaki modele yükseltir.

Model merdiveni: Flash → Pro → Opus. Her aşamada git snapshot alır, başarısız olursa WIP restore eder.

### İzleme
```bash
agykit status                  # tek satır: hesap | model | kota özeti
agykit quota                   # model kota tablosu (5dk cache)
agykit quota --refresh         # cache yenile
agykit quota --status          # script için tek satır
agykit log [N]                 # son N ops log satırı (default: 20)
agykit dash [--port N]         # kullanım dashboard'u (localhost:7373)
```

### Ops Log (`~/.gemini/agykit-ops.log`)
Her `run` / `do-escalate` çağrısını JSONL formatında loglar:
```json
{"ts":"2026-05-31T10:00:00Z","cmd":"run","status":"success","account":"x@y.com","model":"","prompt":"..."}
```
`status` değerleri: `success` | `quota-rotate` | `exhausted` | `verify-failed` | `all-exhausted`  
Rotasyon: dosya >512KB olduğunda son 400 satıra kırpılır.

### Proje Kurulumu
```bash
agykit init                    # .agykit.conf + CLAUDE_AGY_SYSTEM.md scaffold
agykit doctor                  # bağımlılık + yapılandırma kontrolü
agykit doctor --fix            # otomatik düzeltilebilir sorunları çöz
```

### Konfigürasyon (`.agykit.conf` veya env)
| Değişken | Açıklama | Default |
|---|---|---|
| `AGYKIT_VERIFY` | verify komutu (`do-escalate` için) | — |
| `AGYKIT_SYSTEM` | sistem bağlam dosyası yolu | — |
| `AGYKIT_FLAGS` | agy'ye ek flagler | `--dangerously-skip-permissions` |
| `AGYKIT_TIMEOUT` | `--print-timeout` değeri | `15m` |
| `AGYKIT_TERSE` | çıktı kısaltma seviyesi | `ultra` |

## Delege Kuralları (agy için)

Bir görev `agykit do-escalate` veya `run` ile devredildiğinde:
- Verilen plan/test kontratına birebir uy.
- Testleri silme/değiştirme/zayıflatma.
- `git` komutu çalıştırma.
- Yalnızca implementation dosyalarını düzenle.
