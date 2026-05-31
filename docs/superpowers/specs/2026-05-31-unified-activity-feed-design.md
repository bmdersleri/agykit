# Birleşik Aktivite Akışı — Tasarım Spec'i

**Tarih:** 2026-05-31
**Durum:** Onaylandı (kullanıcı incelemesi bekleniyor)
**Kapsam:** Dashboard widget — mevcut "İşlem Günlüğü" + "CC Aktivitesi" widget'larını tek birleşik kronolojik feed ile değiştir.

## 1. Amaç

agy ops olaylarını (`run` / `do-escalate`) ve Claude Code prompt'larını tek bir
ters-kronolojik (newest-first) zaman çizelgesinde birleştir. Canlı SSE ile üste
güncellenir. İki ayrı widget yerine tek kart → daha az dağınıklık, tek bakışta
"ne oldu" görünümü.

## 2. Karar Özeti (kullanıcı onaylı)

| Karar | Seçim |
|---|---|
| Yerleşim | İki widget'ı **birleştir** (replace) |
| latest_stats özet satırı | **Kalsın** (feed üstünde header) |
| Satır sayısı | **25** |
| Kaynak filtresi | **Var** — agy / CC / hepsi toggle |
| Prompt snippet | Kısa göster, **tıklayınca tam metin** |

## 3. Veri Kaynakları (mevcut, değişmez)

### `collectors.ops_log()` → `{entries, total, warning?}`
Her entry: `{ts, cmd, status, account, model, prompt}`
- `ts`: ISO-8601 UTC string, ör. `"2026-05-31T10:00:00Z"`
- `cmd`: `run` | `do-escalate`
- `status`: `success` | `quota-rotate` | `exhausted` | `verify-failed` | `all-exhausted`

### `collectors.cc_activity()` → `{recent_prompts, latest_stats, warning?}`
- `recent_prompts[]`: `{display, timestamp, project, session_id}` — `timestamp` epoch (sıralama desc)
- `latest_stats`: `{available, date, messages, sessions, tool_calls}` — günlük agregat, **olay değil**

> ⚠️ **Doğrulanacak:** `recent_prompts[].timestamp` birimi (saniye mi milisaniye mi).
> Mevcut `cc_activity` ham sıralama yapıyor; merge öncesi her iki kaynak **saniyeye**
> normalize edilmeli. Birim implementasyonda `~/.claude/history.jsonl` örneğinden teyit edilir.

## 4. Mimari

```
                    /api/activity-feed
                           │
                  collectors.activity_feed(limit=25)
                     │                    │
              ops_log(limit)        cc_activity(limit)
                     │                    │
            agy event[]            cc event[] + latest_stats
                     └────── merge ───────┘
                       sort ts_epoch DESC
                          truncate 25
                             │
              {events:[...], latest_stats:{...}, warning?}
                             │
        app.js loadActivityFeed() → render (#activityFeedCard)
              ├─ summary header (latest_stats)
              ├─ filter toggle (agy/cc/all) — client-side
              └─ feed rows (click → full prompt)
```

## 5. Bileşenler

### 5.1 `collectors.py` — `activity_feed()`

```python
def activity_feed(limit: int = 25, *, log_path=None,
                  history_path=None, stats_path=None) -> dict:
    """agy ops olayları + CC prompt'larını birleşik kronolojik feed olarak döndür."""
```

Davranış:
1. `ops_log(limit=limit, log_path=log_path)` çağır.
2. `cc_activity(limit=limit, history_path=history_path, stats_path=stats_path)` çağır.
3. agy entry → ortak olay:
   `{ts_epoch, kind:"agy", cmd, status, model, account, prompt}`
   - `ts` ISO parse: `datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")` UTC → epoch.
   - Parse edilemeyen/eksik `ts` → `ts_epoch=0` (en alta düşer, görünür kalır).
4. cc prompt → ortak olay:
   `{ts_epoch, kind:"cc", display, project, session_id}`
   - `timestamp` saniyeye normalize.
5. İki listeyi birleştir, `ts_epoch` DESC sırala, `limit`'e (25) kes.
6. Döner: `{"events": [...], "latest_stats": {...}, "warning": ...}`
   - `latest_stats` cc_activity'den aynen geçer.
   - `warning`: alt collector'lardan gelen uyarıları birleştir (varsa).

Kısıt: yalnız stdlib (`datetime`, `json`, `os`). Yeni pip yok. Salt-okunur dosya erişimi.

### 5.2 `server.py` — routing

- **Ekle:** `/api/activity-feed` → `collectors.activity_feed(limit=...)` (`serve_json`).
  - `limit` query param desteği (default 25), mevcut ops-log/cc-activity route'larındaki gibi.
- **Kaldır:** `/api/ops-log` ve `/api/cc-activity` route'ları (widget'lar gidiyor).
  - Collector fonksiyonları **silinmez** — `activity_feed` içeride kullanıyor + testler doğruluyor.
- **Doğrula:** `get_current_mtime_state()` ops log (`~/.gemini/agykit-ops.log`) ve
  `~/.claude/history.jsonl` mtime'larını izliyor mu? İzlemiyorsa ekle → yeni aktivitede SSE "refresh" atar.

### 5.3 `index.html`

- **Sil:** `#opsLogCard` ve `#ccActivityCard` blokları.
- **Ekle:** tek `#activityFeedCard` (`info-card` deseni):
  - Başlık `<h3 class="info-card-title">Aktivite Akışı</h3>` + canlı nokta (mevcut desen).
  - `#activityFeedSummary` — latest_stats özet satırı (tarih · mesaj · oturum · tool).
  - `#activityFeedFilter` — toggle: agy / CC / hepsi.
  - `#activityFeedBody` — kaydırılır liste (`max-height`, ~25 satır).

### 5.4 `app.js`

- **Sil:** `loadOpsLog()`, `loadCcActivity()`.
- **Ekle:** `loadActivityFeed()`:
  - `fetch('/api/activity-feed')` → veriyi modül-kapsamlı değişkende sakla (filtre için).
  - `renderActivityFeed(filter)` — saklanan datadan render; filtre client-side (refetch yok).
  - Satır render: kaynak badge (agy ▲ / CC ◆), status renk, relative-time, kısa prompt/display.
  - Satır tıkla → **inline genişlet** (satır altında tam `prompt`/`display` metni; modal yok). Tekrar tıkla → kapanır.
  - Relative-time helper: `şimdi` / `Ndk` / `Nsa` / `Ngün` (ts_epoch'tan client-side).
- **Bağla:**
  - init bloğu (~satır 1065-1067): `loadOpsLog`+`loadCcActivity` → `loadActivityFeed`.
  - SSE refresh bloğu (~satır 1093-1094): aynı değişim.
  - Filtre toggle change → `renderActivityFeed(seçilen)`.

### 5.5 `style.css`

- `.af-row` feed satırı, `.af-badge-agy` (mavi), `.af-badge-cc` (mor).
- Status renkleri: `.af-ok` yeşil, `.af-warn` amber, `.af-fail` kırmızı.
- `.af-filter` toggle, `.af-time` (soluk), `.af-row--expanded` tam metin.
- Mevcut `info-card` / değişken paletiyle uyumlu.

## 6. Hata Yönetimi

- Ops log / history dosyası yok → alt collector `warning` döndürür; feed boş gösterir + uyarı satırı.
- Bozuk JSONL satırları → `ops_log`/`cc_activity` zaten atlıyor (miras alınır).
- ISO parse hatası → o olay `ts_epoch=0`, feed sonunda görünür (sessiz düşmez).
- API hata → frontend mevcut diğer widget'lardaki gibi hata mesajı gösterir.

## 7. Test Stratejisi (`tests/`)

Yeni pytest — `activity_feed`:
- **merge sırası:** agy + cc olayları ts_epoch DESC sıralı.
- **ts normalize:** ISO-8601 Z doğru epoch'a; cc epoch (sn) doğru hizalanır; karışık birim doğru sıralanır.
- **limit:** 30 olay verildiğinde 25'e kesilir; en yeni 25.
- **latest_stats passthrough:** cc_activity latest_stats aynen döner.
- **boş/eksik dosya:** warning döner, events `[]`.
- **bozuk satır skip:** ops_log malformed satırları feed'i bozmaz.
- **ts_epoch=0 fallback:** parse edilemeyen ts en alta, görünür.

Mevcut `ops_log` / `cc_activity` collector testleri **yeşil kalmalı**.
Bash güvenlik süitleri (`bash tests/run.sh`) etkilenmez — `agykit log` dokunulmaz.

Çalıştırma:
```bash
python3 -m pytest tests -q
bash tests/run.sh
```

## 8. Kısıt Uyumu (agykit CLAUDE.md)

- ✅ Sıfır pip — yalnız stdlib (`datetime` eklenir).
- ✅ `127.0.0.1` bind, `~/.claude` + `~/.gemini` salt-okunur.
- ✅ Web katmanı vanilla JS/HTML/CSS — framework yok.
- ✅ `agykit` bash betiği değişmez (`agykit log` ops log'u doğrudan okur, bağımsız).

## 9. Kapsam Dışı (YAGNI)

- Sonsuz kaydırma / sayfalama — 25 satır sabit.
- Sunucu-tarafı filtre — filtre client-side.
- Yeni olay türleri (quota değişimi vb.) — yalnız mevcut iki kaynak.
- Feed arama / export.
```
