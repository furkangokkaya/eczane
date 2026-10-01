#!/usr/bin/env python3
"""GitHub Actions — bitlis_pharmacy_cache.json doğrulama."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bitlis_services.pharmacy import (  # noqa: E402
    ECZANELERI_CITY_URL,
    ECZANELERI_DISTRICT_KEYS,
    MIN_ACTIVE_DISTRICTS,
    is_pharmacy_cache_complete,
)

CACHE = ROOT / "bitlis_pharmacy_cache.json"
TZ_TR = ZoneInfo("Europe/Istanbul")


def main() -> int:
    today = datetime.now(TZ_TR).strftime("%Y-%m-%d")
    data = json.loads(CACHE.read_text(encoding="utf-8"))
    print(
        f"date={data.get('date')} expected={today} total={data.get('total')} "
        f"source={data.get('source')}",
        flush=True,
    )

    if "eczaneleri.org" not in (data.get("source") or "").lower():
        print("HATA: kaynak bitlis.eczaneleri.org degil", file=sys.stderr)
        return 1
    if str(data.get("date") or "") != today:
        print(f"HATA: tarih uyumsuz ({data.get('date')} != {today})", file=sys.stderr)
        return 1
    if not is_pharmacy_cache_complete(data):
        keys = {
            d.get("key")
            for d in (data.get("districts") or [])
            if int(d.get("count") or 0) >= 1
        }
        missing = sorted(ECZANELERI_DISTRICT_KEYS - keys)
        print(
            f"HATA: eksik liste (total={data.get('total')}, "
            f"min_ilce={MIN_ACTIVE_DISTRICTS - 1}, eksik={missing})",
            file=sys.stderr,
        )
        return 1

    print(f"OK: eczaneleri cache ({ECZANELERI_CITY_URL})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
