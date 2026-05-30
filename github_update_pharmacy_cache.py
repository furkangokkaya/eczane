#!/usr/bin/env python3
"""GitHub Actions — günlük nöbetçi eczane cache güncelleme."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bitlis_services.pharmacy import (  # noqa: E402
    MIN_PHARMACY_TOTAL,
    fetch_duty_pharmacies,
    is_pharmacy_cache_complete,
)

OUT = ROOT / "bitlis_pharmacy_cache.json"
TZ_TR = ZoneInfo("Europe/Istanbul")


def _today_tr() -> str:
    return datetime.now(TZ_TR).strftime("%Y-%m-%d")


def main() -> int:
    today = _today_tr()
    print(f"TR tarih: {today}", flush=True)

    data = fetch_duty_pharmacies(
        github_only=False,
        allow_stale_fallback=False,
        for_daily_publish=True,
    )
    if not data.get("ok"):
        print("HATA:", data.get("error") or "eczane verisi alınamadı", file=sys.stderr)
        return 1
    if str(data.get("date") or "") != today:
        print(
            f"HATA: tarih uyumsuz (beklenen {today}, gelen {data.get('date')})",
            file=sys.stderr,
        )
        return 1
    if not is_pharmacy_cache_complete(data):
        print(
            f"HATA: eksik eczane listesi (total={data.get('total')}, "
            f"min={MIN_PHARMACY_TOTAL}) — cache yazilmadi",
            file=sys.stderr,
        )
        return 1

    payload = {k: v for k, v in data.items() if not str(k).startswith("_")}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {data.get('total', 0)} eczane - {today} -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
