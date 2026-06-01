# Bilgi Adaylıkları

Denetçi incelemesi bekleyen aday öğrenmeler.
Format: `- [GGAAYY] /kaynak: [öğrenim] | Kanıt: [kaynak]`

- [053126] /wrap-up: `mcp__plugin_*` wildcard tool adı düzeyinde çalışmıyor — her MCP aracı `permissions.allow`'a explicit eklenmeli | Kanıt: ctx_execute_file ve playwright tools prompt istemeye devam etti, explicit ekledikten sonra çözüldü
- [053126] /wrap-up: Ağır skill yüklemeleri (update-config ~3000 satır JSON şeması) context'i hızla doldurur ve compact summary'ye girer — `/clear` sonrası bile yüksek başlangıç context'i oluşur | Kanıt: update-config skill yüklendikten sonra context %90+ çıktı
