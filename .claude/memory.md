# Hafıza — agykit

## Şimdi

- RTK Tasarruf + CC Aktivitesi widget'ları tamamlandı. Son commit: `feat(dashboard): add RTK Tasarruf and CC Aktivitesi widgets`
- Dashboard canlı: `python3 dashboard/server.py --port 7373`
- 19/19 test yeşil

## Açık Konular

- Yok

## Son Kararlar

- [053126] RTK veri dosyası yok → `subprocess.run(['rtk', 'gain'])` parse; in-process cache YOK (test izolasyonu için)
- [053126] stats-cache.json 1-2 gün geride → en son mevcut tarihi göster (`latest_stats`), today/yesterday hardcode değil
- [053126] agy do-escalate Gemini Flash'ta çok uzun bekledi → iptal edip mimar (Claude) yazdı
- [053126] Statusline her zaman render edilir; `/api/statusline` email → OAuth 401 fallback
- [053126] `mcp__plugin_*` wildcard tool adı düzeyinde çalışmıyor — explicit tool adları gerekiyor
- [053026] agy print-mode güvenilmez → RED testleri her zaman mimar (Claude) yazar; agy sadece implementation

## Engeller

- Yok
