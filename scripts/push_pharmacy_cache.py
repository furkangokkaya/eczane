#!/usr/bin/env python3
"""GitHub Actions — cache push (yarış/çakışmaya dayanıklı)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "bitlis_pharmacy_cache.json"
TZ_TR = ZoneInfo("Europe/Istanbul")
sys.path.insert(0, str(ROOT))


def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def _today_tr() -> str:
    return datetime.now(TZ_TR).strftime("%Y-%m-%d")


def _cache_ok(data: dict) -> bool:
    from bitlis_services.pharmacy import is_pharmacy_cache_complete

    return (
        str(data.get("date") or "") == _today_tr()
        and "eczaneleri.org" in str(data.get("source") or "").lower()
        and is_pharmacy_cache_complete(data)
    )


def _remote_cache_bytes() -> bytes | None:
    r = _run(["git", "show", "origin/main:bitlis_pharmacy_cache.json"])
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    return r.stdout.encode("utf-8")


def _remote_cache_ok() -> bool:
    raw = _remote_cache_bytes()
    if not raw:
        return False
    try:
        return _cache_ok(json.loads(raw.decode("utf-8")))
    except Exception:
        return False


def _configure_git() -> None:
    _run(["git", "config", "user.name", "github-actions[bot]"])
    _run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])


def _abort_rebase() -> None:
    _run(["git", "rebase", "--abort"])


def main() -> int:
    if not CACHE.is_file():
        print("HATA: bitlis_pharmacy_cache.json yok", file=sys.stderr)
        return 1

    local = json.loads(CACHE.read_text(encoding="utf-8"))
    if not _cache_ok(local):
        print("HATA: yerel cache dogrulanamadi", file=sys.stderr)
        return 1

    _configure_git()
    fetch = _run(["git", "fetch", "origin", "main"])
    if fetch.returncode != 0:
        print(fetch.stderr or fetch.stdout, file=sys.stderr)
        return 1

    if _remote_cache_ok():
        print("Remote zaten bugunku tam cache — push atlandi.")
        return 0

    today = _today_tr()
    _run(["git", "add", "bitlis_pharmacy_cache.json"])
    if _run(["git", "diff", "--staged", "--quiet"]).returncode == 0:
        print("Staged degisiklik yok.")
        return 0

    commit = _run(
        ["git", "commit", "-m", f"chore: eczane cache {today} [bot]"],
    )
    if commit.returncode != 0:
        print(commit.stderr or commit.stdout, file=sys.stderr)
        return 1

    for attempt in range(1, 6):
        push = _run(["git", "push", "origin", "HEAD:main"])
        if push.returncode == 0:
            print("Push OK.")
            return 0

        print(f"Push deneme {attempt}/5 basarisiz, senkron...", flush=True)
        _run(["git", "fetch", "origin", "main"])

        if _remote_cache_ok():
            _run(["git", "reset", "--hard", "origin/main"])
            print("Baska calisma push etmis — remote bugunku cache OK.")
            return 0

        rebase = _run(["git", "pull", "--rebase", "origin", "main"])
        if rebase.returncode != 0:
            _run(["git", "checkout", "--ours", "bitlis_pharmacy_cache.json"])
            _run(["git", "add", "bitlis_pharmacy_cache.json"])
            cont = _run(["git", "rebase", "--continue"])
            if cont.returncode != 0:
                _abort_rebase()
                _run(["git", "reset", "--hard", "origin/main"])
                CACHE.write_text(
                    json.dumps(local, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                _run(["git", "add", "bitlis_pharmacy_cache.json"])
                _run(["git", "commit", "-m", f"chore: eczane cache {today} [bot]"])

        time.sleep(min(30, 5 * attempt))

    print("HATA: push 5 denemede basarisiz", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
