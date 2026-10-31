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
    BITLISECZA_URL,
    ECZANELERI_CITY_URL,
    MIN_ACTIVE_DISTRICTS,
    is_pharmacy_cache_complete,
    pharmacy_missing_district_keys,
)

CACHE = ROOT / "bitlis_pharmacy_cache.json"
TZ_TR = ZoneInfo("Europe/Istanbul")


def _ok_source(source: str) -> bool:
    s = (source or "").lower()
    return (
        "bitlisecza" in s
        or "eczaneleri.org" in s
        or "hurriyet" in s
        or "eczaneler.gen.tr" in s
        or "merged" in s
    )


def main() -> int:
    today = datetime.now(TZ_TR).strftime("%Y-%m-%d")
    data = json.loads(CACHE.read_text(encoding="utf-8"))
    print(
        f"date={data.get('date')} expected={today} total={data.get('total')} "
        f"source={data.get('source')}",
        flush=True,
    )

    if not _ok_source(str(data.get("source") or "")):
        print(f"HATA: beklenmeyen kaynak: {data.get('source')}", file=sys.stderr)
        return 1
    if str(data.get("date") or "") != today:
        print(f"HATA: tarih uyumsuz ({data.get('date')} != {today})", file=sys.stderr)
        return 1
    if not is_pharmacy_cache_complete(data):
        missing = pharmacy_missing_district_keys(data)
        print(
            f"HATA: eksik liste (total={data.get('total')}, "
            f"min_ilce={MIN_ACTIVE_DISTRICTS}, eksik={missing})",
            file=sys.stderr,
        )
        return 1

    print(f"OK: eczane cache ({data.get('source') or BITLISECZA_URL or ECZANELERI_CITY_URL})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
