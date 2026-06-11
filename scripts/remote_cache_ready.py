#!/usr/bin/env python3
"""Remote cache bugün hazırsa GitHub Actions scrape adımını atla."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bitlis_services.pharmacy import is_pharmacy_cache_complete  # noqa: E402

TZ_TR = ZoneInfo("Europe/Istanbul")


def main() -> int:
    today = datetime.now(TZ_TR).strftime("%Y-%m-%d")
    r = subprocess.run(
        ["git", "show", "origin/main:bitlis_pharmacy_cache.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    ready = False
    if r.returncode == 0 and (r.stdout or "").strip():
        try:
            data = json.loads(r.stdout)
            ready = (
                str(data.get("date") or "") == today
                and "eczaneleri.org" in str(data.get("source") or "").lower()
                and is_pharmacy_cache_complete(data)
            )
        except Exception:
            ready = False

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"ready={'true' if ready else 'false'}\n")

    if ready:
        print(f"Remote cache hazir ({today}) — scrape atlanacak.")
        return 0
    print(f"Remote cache guncellenmeli (bugun: {today}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
