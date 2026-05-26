# Bitlis Eczane Cache

Bu küçük repo sadece nöbetçi eczane JSON dosyasını üretmek içindir.
Telegram, Instagram, Facebook veya bot tokeni içermez.

## Kurulum

1. Bu klasörün içeriğini yeni bir GitHub reposuna yükle.
2. GitHub'da `Settings > Actions > General > Workflow permissions` bölümünden `Read and write permissions` seç.
3. `Actions` sekmesinden `Update Pharmacy Cache` workflow'unu manuel çalıştır.
4. Başarılı çalışırsa `bitlis_pharmacy_cache.json` güncellenir.

## Ana Bot Ayarı

Ana botun `bitlis_config.json` dosyasında `remote_url` alanını şu formata getir:

```json
"pharmacy": {
  "remote_url": "https://raw.githubusercontent.com/KULLANICI_ADIN/REPO_ADI/main/bitlis_pharmacy_cache.json",
  "remote_token": "",
  "github_cache_file": "bitlis_pharmacy_cache.json"
}
```

## Not

GitHub Actions için VDS gerekmez. GitHub kendi runner'ında scrape yapar.
Eğer kaynak site GitHub IP'lerini engellerse workflow hata verir; bu durumda JSON güncellenmez.
