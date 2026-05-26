"""GitHub Actions için günlük nöbetçi eczane cache üretici.

Bu script paylaşım yapmaz. Sadece eczaneler.gen.tr verisini çeker ve
`bitlis_pharmacy_cache.json` dosyasını günceller.
"""
from __future__ import annotations

import json
from pathlib import Path

from bitlis_services.pharmacy import fetch_duty_pharmacies


ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "bitlis_pharmacy_cache.json"


def main() -> int:
    data = fetch_duty_pharmacies(use_remote=False)
    if not data.get("ok"):
        print(f"Eczane verisi alınamadı: {data.get('error')}")
        return 1

    CACHE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Eczane cache güncellendi: "
        f"{data.get('date')} · {data.get('total', 0)} eczane"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
