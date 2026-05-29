# Bitlis nöbetçi eczane cache (GitHub repo)

Bu klasörün içeriğini **`furkangokkaya/eczane`** reposunun köküne kopyalayın.
Bot yalnızca şu dosyayı okur:

`https://raw.githubusercontent.com/furkangokkaya/eczane/main/bitlis_pharmacy_cache.json`

## İlk kurulum

1. `deploy/eczane_repo/` içindeki tüm dosyaları eczane reposuna commit edin.
2. GitHub → Actions → **Pharmacy cache daily** → **Run workflow** (manuel test).
3. `bitlis_pharmacy_cache.json` içindeki `date` alanı bugünün tarihi olmalı.

## Acil güncelleme (bugün paylaşım kaçtıysa)

Yerel makinede (bu proje kökünde):

```powershell
python github_update_pharmacy_cache.py
```

Oluşan `bitlis_pharmacy_cache.json` dosyasını eczane reposuna push edin.
Bot 15 dakikada bir kaçan eczane paylaşımını tekrar dener.
