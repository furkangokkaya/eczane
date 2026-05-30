# Bitlis nöbetçi eczane cache (GitHub)

Bot **yalnızca** bu dosyayı okur:

`https://raw.githubusercontent.com/furkangokkaya/eczane/main/bitlis_pharmacy_cache.json`

## Otomatik güncelleme (Actions)

Workflow: **Pharmacy cache daily** — İstanbul saati 07:00, 11:30–12:20 ve UTC yedek.

Manuel: GitHub → Actions → Run workflow.

## Sunucu tetikleme (önerilir)

Cache eskiyse bot GitHub Actions’ı API ile başlatır. Sunucuda:

1. GitHub → Settings → Developer settings → Fine-grained token
2. Repository access: `furkangokkaya/eczane`
3. Permissions: **Actions** (read and write), **Contents** (read and write — sunucu upload icin)
4. Token’ı sunucuda ortam değişkeni olarak verin:

```bash
export GITHUB_PHARMACY_PAT="github_pat_..."
```

veya `bitlis_config.json` içinde `pharmacy.github.pat` (dosyayı paylaşmayın).

## GitHub Actions ve 403

`ubuntu-latest` IP'leri `eczaneler.gen.tr` tarafindan siklikla **403** alir; kismi scrape (1 eczane) artik **commit edilmez** (min 7 eczane + 7 ilce).

**Onerilen:** Bot sunucusu cache'i canli ceker ve PAT ile `bitlis_pharmacy_cache.json` yukler (`server_upload_on_incomplete: true`). PAT'te **Contents: write** sart.

Alternatif: [self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners) (Turkiye VDS) ile ayni workflow.

## Yerel test

```bash
pip install -r requirements.txt
python github_update_pharmacy_cache.py
```
