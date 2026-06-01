# Bilgi Tabanı — agykit

Proje geneli öğrenilmiş kurallar. Her oturumda okunur.
Girişler zorunlu kısıtlamalardır, öneri değil.

## Kaynak Hiyerarşisi

- `[Kaynak: kullanıcı müdahalesi GGAAYY]` — Kullanıcı açıkça düzeltti
- `[Kaynak: ampirik GGAAYY]` — Test veya veri ile doğrulandı
- `[Kaynak: agent çıkarımı GGAAYY]` — Agent gözlemi, Denetçi onaylı

## Kesin Kurallar

- Sıfır pip bağımlılığı — yalnızca Python 3 stdlib. `[Kaynak: kullanıcı müdahalesi 053026]`
- `agykit` bash stili: `cmd_*` fonksiyonları + dispatch case. Framework ekleme. `[Kaynak: kullanıcı müdahalesi 053026]`
- Web katmanı vanilla JS/HTML/CSS kalır. React veya başka framework girilmez. `[Kaynak: kullanıcı müdahalesi 053026]`
- agy print-mode güvenilmez (9dk hang riski). RED testleri Claude yazar; agy sadece implementation. `[Kaynak: ampirik 053026]`

## Platform ve Araç Kuralları

- Dashboard sunucusu `127.0.0.1` bağlar, dışarıya açılmaz. `[Kaynak: kullanıcı müdahalesi 053026]`
- `/api/active-account` → OAuth, 401 dönebilir. `/api/statusline` → local file, her zaman çalışır. `[Kaynak: ampirik 053126]`
- `agent_state` değerleri: `"idle"` veya diğer string'ler (ör. `"working"`) — `collectors.agy_statusline_snapshot()` üretir. `[Kaynak: ampirik 053126]`

## Proje Kalıpları

- `gearPath(cx, cy, n, Ro, Ri, Rh)` — JS ile SVG dişli yolu hesabı. Her `loadStatusline()` çağrısında inline üretir (DOM ref yok). `[Kaynak: agent çıkarımı 053126]`
- SSE endpoint `loadStatusline()` üzerinden çalışır; sayfa yenilenmeden canlı güncelleme. `[Kaynak: ampirik 053126]`

## Yapılandırma ve İzin Kuralları

- `mcp__plugin_*` wildcard `permissions.allow`'da çalışmıyor — her MCP aracı ayrı satırda explicit eklenmeli (ör. `mcp__plugin_context-mode__ctx_execute`). `[Kaynak: ampirik 053126]`
- Ağır skill yüklemeleri (ör. update-config ~3000 satır JSON şeması) context'i hızla doldurur; `/clear` planlanmadan önce skill boyutları göz önünde bulundurulmalı. `[Kaynak: ampirik 053126]`

## Bilinen Hata Kalıpları

- `loadStatusline()` → `activeEmail` koşuluna bağlanırsa OAuth 401'de statusline hiç görünmüyor. Her zaman bağımsız çağır. `[Kaynak: ampirik 053126]`
- SVG `transform-origin` inline style olarak verilmeli (`style="transform-origin:Xpx Ypx"`); CSS class'a taşınırsa animasyon merkezi kayıyor. `[Kaynak: ampirik 053126]`
