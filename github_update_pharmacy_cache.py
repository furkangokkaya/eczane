#!/usr/bin/env python3
"""GitHub Actions — günlük nöbetçi eczane cache güncelleme."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bitlis_services.pharmacy import (  # noqa: E402
    BITLISECZA_URL,
    ECZANELERI_CITY_URL,
    MIN_ACTIVE_DISTRICTS,
    _fetch_from_bitlisecza,
    _fetch_from_eczaneleri,
    _scrape_live_pharmacies,
    is_pharmacy_cache_complete,
    pharmacy_missing_district_keys,
)

OUT = ROOT / "bitlis_pharmacy_cache.json"
TZ_TR = ZoneInfo("Europe/Istanbul")


def _today_tr() -> str:
    return datetime.now(TZ_TR).strftime("%Y-%m-%d")


def _acceptable_source(source: str) -> bool:
    s = (source or "").lower()
    return (
        "bitlisecza" in s
        or "eczaneleri.org" in s
        or "hurriyet" in s
        or "eczaneler.gen.tr" in s
        or "merged" in s
    )


def main() -> int:
    today = _today_tr()
    print(f"TR tarih: {today}", flush=True)

    now = datetime.now(TZ_TR)
    data: dict = {}
    last_error = ""
    for attempt in range(1, 4):
        # 1) Resmi oda
        data = _fetch_from_bitlisecza(now, for_daily_publish=True)
        if not (
            data.get("ok")
            and is_pharmacy_cache_complete(data)
            and not pharmacy_missing_district_keys(data)
        ):
            # 2) Birleşik scrape (resmi + yedekler)
            data = _scrape_live_pharmacies(now, for_daily_publish=True)
        if not (data.get("ok") and is_pharmacy_cache_complete(data)):
            data = _fetch_from_eczaneleri(now, for_daily_publish=True)

        if (
            data.get("ok")
            and str(data.get("date") or "") == today
            and is_pharmacy_cache_complete(data)
        ):
            break
        last_error = str(data.get("error") or "eczane verisi alınamadı")
        print(f"Uyari: deneme {attempt}/3 basarisiz: {last_error}", flush=True)
        if attempt < 3:
            time.sleep(10 * attempt)

    if not data.get("ok") or not is_pharmacy_cache_complete(data):
        if OUT.exists():
            try:
                cached = json.loads(OUT.read_text(encoding="utf-8"))
                if (
                    str(cached.get("date") or "") == today
                    and is_pharmacy_cache_complete(cached)
                ):
                    print(
                        "Uyari: Canli scrape basarisiz, bugunku mevcut cache korunuyor:",
                        last_error or data.get("error") or "bilinmiyor",
                        flush=True,
                    )
                    return 0
            except Exception:
                pass
        print("HATA:", data.get("error") or "eczane verisi alınamadı", file=sys.stderr)
        return 1

    if str(data.get("date") or "") != today:
        print(
            f"HATA: tarih uyumsuz (beklenen {today}, gelen {data.get('date')})",
            file=sys.stderr,
        )
        return 1

    if not _acceptable_source(str(data.get("source") or "")):
        print(f"HATA: beklenmeyen kaynak: {data.get('source')}", file=sys.stderr)
        return 1

    miss = pharmacy_missing_district_keys(data)
    if len(miss) > 1:
        print(
            f"HATA: eksik eczane listesi (total={data.get('total')}, "
            f"min_ilce={MIN_ACTIVE_DISTRICTS}, eksik={miss}) — cache yazilmadi",
            file=sys.stderr,
        )
        return 1

    payload = {k: v for k, v in data.items() if not str(k).startswith("_")}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    src = data.get("source") or BITLISECZA_URL or ECZANELERI_CITY_URL
    print(
        f"OK: {data.get('total', 0)} eczane — {today} — {src} -> {OUT.name}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
