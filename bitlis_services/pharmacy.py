"""
Bitlis nöbetçi eczaneler — günlük liste (yalnızca Hürriyet Bitlis sayfası).
"""
from __future__ import annotations

import logging
import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("bitlis_platform.pharmacy")

SOURCE_URL = "https://www.eczaneler.gen.tr/nobetci-bitlis"
SOURCE_URLS = (
    SOURCE_URL,
    f"{SOURCE_URL}/",
    "https://www.eczaneler.gen.tr/",
)
CACHE_PATH = Path(__file__).resolve().parents[1] / "bitlis_pharmacy_cache.json"
DEFAULT_GITHUB_CACHE_URL = (
    "https://raw.githubusercontent.com/furkangokkaya/eczane/main/bitlis_pharmacy_cache.json"
)
HURRIYET_CITY_URL = "https://www.hurriyet.com.tr/nobetci-eczaneler/bitlis/"
# Hürriyet Bitlis sayfasındaki ilçeler (Merkez ayrı listelenmez).
HURRIYET_DISTRICT_KEYS = frozenset({
    "adilcevaz", "ahlat", "guroymak", "hizan", "mutki", "tatvan",
})
ECZANELERI_CITY_URL = "https://bitlis.eczaneleri.org/"
# bitlis.eczaneleri.org sayfasında merkez + 5 ilçe listeleniyor (Mutki her gün olmayabilir).
ECZANELERI_DISTRICT_KEYS = frozenset({
    "adilcevaz", "ahlat", "guroymak", "hizan", "merkez", "tatvan",
})
_ECZANELERI_PHONE_RE = re.compile(r"Telefon\s*:\s*(0\d{10})", re.I)

DISTRICT_SOURCE_URLS = {
    "merkez": "https://www.eczaneler.gen.tr/nobetci-bitlis-merkez",
    "mutki": "https://www.eczaneler.gen.tr/nobetci-bitlis-mutki",
    "ahlat": "https://www.eczaneler.gen.tr/nobetci-bitlis-ahlat",
    "adilcevaz": "https://www.eczaneler.gen.tr/nobetci-bitlis-adilcevaz",
    "guroymak": "https://www.eczaneler.gen.tr/nobetci-bitlis-guroymak",
    "hizan": "https://www.eczaneler.gen.tr/nobetci-bitlis-hizan",
    "tatvan": "https://www.eczaneler.gen.tr/nobetci-bitlis-tatvan",
}

DISTRICT_ORDER = [
    ("merkez", "Merkez"),
    ("mutki", "Mutki"),
    ("ahlat", "Ahlat"),
    ("adilcevaz", "Adilcevaz"),
    ("guroymak", "Güroymak"),
    ("hizan", "Hizan"),
    ("tatvan", "Tatvan"),
]

# Bitlis: 7 ilçe; genelde ilçe başına 1 nöbetçi (Tatvan bazen 2 → toplam 7–8).
MIN_PHARMACY_TOTAL = 7
# Bazı günler bir ilçede nöbetçi olmayabilir (ör. Mutki).
MIN_ACTIVE_DISTRICTS = 6
_EXPECTED_DISTRICT_KEYS = frozenset(k for k, _ in DISTRICT_ORDER)

_NO_DUTY_RE = re.compile(
    r"nöbetçi\s+eczane\s+kaydı\s+bulunamadı|nobetci\s+eczane\s+kaydi\s+bulunamadi",
    re.I,
)


def _text_indicates_no_duty(text: str) -> bool:
    return bool(_NO_DUTY_RE.search(text or ""))


def is_pharmacy_cache_complete(data: Dict[str, Any]) -> bool:
    """GitHub/bot için yeterli nöbetçi listesi (bir ilçe nöbetsiz olabilir)."""
    if not data or not data.get("ok"):
        return False
    districts = data.get("districts") or []
    source = (data.get("source") or "").lower()
    if "hurriyet" in source:
        expected = HURRIYET_DISTRICT_KEYS
    elif "eczaneleri.org" in source:
        expected = ECZANELERI_DISTRICT_KEYS
    else:
        expected = _EXPECTED_DISTRICT_KEYS
    keys_present = {
        str(d.get("key") or "")
        for d in districts
        if str(d.get("key") or "") in expected
    }
    if not expected.issubset(keys_present):
        return False
    total = int(data.get("total") or 0)
    active_districts = sum(
        1 for d in districts if int(d.get("count") or 0) >= 1
    )
    min_active = MIN_ACTIVE_DISTRICTS
    if "hurriyet" in source:
        # Hürriyet: 6 ilçe; birinde nöbetçi olmayabilir (ör. Mutki).
        min_active = MIN_ACTIVE_DISTRICTS - 1
    elif "eczaneleri.org" in source:
        # eczaneleri.org Bitlis görünümünde mutki çoğu gün yok.
        min_active = MIN_ACTIVE_DISTRICTS - 1
    if total < MIN_ACTIVE_DISTRICTS or active_districts < min_active:
        return False
    return total >= MIN_ACTIVE_DISTRICTS


def _github_actions_runner() -> bool:
    import os

    return os.environ.get("GITHUB_ACTIONS", "").lower() in ("true", "1")

DISTRICT_FROM_TEXT = {
    "adilcevaz": "adilcevaz",
    "ahlat": "ahlat",
    "güroymak": "guroymak",
    "guroymak": "guroymak",
    "hizan": "hizan",
    "merkez": "merkez",
    "mutki": "mutki",
    "tatvan": "tatvan",
    "bitlis": "merkez",
}
MONTHS_TR = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan", 5: "Mayıs", 6: "Haziran",
    7: "Temmuz", 8: "Ağustos", 9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}
WEEKDAYS_TR = (
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
)
_MONTH_NAME_TO_NUM = {
    name.lower(): num for num, name in MONTHS_TR.items()
}
for _n, _num in list(MONTHS_TR.items()):
    _MONTH_NAME_TO_NUM[_num[:3].lower()] = _n

PHONE_RE = re.compile(r"0\s*\(\d{3,4}\)\s*[\d\s-]+")
PERIOD_RE = re.compile(
    r"(\d{1,2})\s+(\w+)\s+(\w+)?.*?(gün\s+boyu|akşamından|gününden)",
    re.I,
)


def _browser_headers(referer: str = "https://www.eczaneler.gen.tr/") -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        # br (Brotli) istemeyin — requests brotli paketi olmadan bozuk gövde döner.
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }


_CURL_IMPERSONATES = (
    "chrome131",
    "chrome124",
    "chrome120",
    "chrome110",
    "safari17_0",
    "edge101",
)


class _EczanelerCurlFetcher:
    """curl_cffi oturumu — cookie + TLS; 403 azaltmak için tek oturumda ısınma."""

    def __init__(self) -> None:
        self._session: Any = None
        self._impersonate: str = ""

    def _open_session(self) -> None:
        from curl_cffi import requests as curl_requests

        last_error: Optional[Exception] = None
        for imp in _CURL_IMPERSONATES:
            try:
                sess = curl_requests.Session(impersonate=imp)
                sess.get(
                    "https://www.eczaneler.gen.tr/",
                    headers=_browser_headers(),
                    timeout=35,
                )
                time.sleep(1.2 + random.random())
                sess.get(
                    SOURCE_URL,
                    headers=_browser_headers(SOURCE_URL),
                    timeout=35,
                )
                time.sleep(0.8 + random.random() * 0.7)
                self._session = sess
                self._impersonate = imp
                logger.debug("eczaneler.gen.tr curl oturumu: %s", imp)
                return
            except Exception as e:
                last_error = e
                time.sleep(0.6)
        raise RuntimeError(str(last_error or "curl_cffi oturumu açılamadı"))

    def fetch(self, url: str, *, referer: Optional[str] = None) -> str:
        if self._session is None:
            self._open_session()
        ref = referer or (url if "eczaneler.gen.tr" in url else SOURCE_URL)
        time.sleep(1.0 + random.random() * 1.8)
        r = self._session.get(
            url,
            headers=_browser_headers(ref),
            timeout=40,
            allow_redirects=True,
        )
        r.raise_for_status()
        return r.text


_eczaneler_fetcher: Optional[_EczanelerCurlFetcher] = None


def _reset_eczaneler_curl() -> None:
    global _eczaneler_fetcher
    _eczaneler_fetcher = None


def _curl_fetcher() -> _EczanelerCurlFetcher:
    global _eczaneler_fetcher
    if _eczaneler_fetcher is None:
        _eczaneler_fetcher = _EczanelerCurlFetcher()
    return _eczaneler_fetcher


def _fetch_url_html_curl(url: str, referer: Optional[str] = None) -> str:
    """Öncelik: kalıcı curl oturumu (403'e karşı)."""
    try:
        return _curl_fetcher().fetch(url, referer=referer)
    except ImportError as e:
        raise RuntimeError("curl_cffi yüklü değil; pip install curl_cffi") from e


def _fetch_url_html_browser(url: str, referer: str = "https://www.eczaneler.gen.tr/") -> str:
    """Tek istek yedek — oturumsuz deneme."""
    from curl_cffi import requests as curl_requests

    last_error: Optional[Exception] = None
    for impersonate in _CURL_IMPERSONATES:
        try:
            r = curl_requests.get(
                url,
                headers=_browser_headers(referer),
                timeout=35,
                impersonate=impersonate,
            )
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_error = e
    raise RuntimeError(str(last_error or "curl_cffi isteği başarısız"))


def _fetch_url_html(_session: requests.Session, url: str) -> str:
    """requests genelde 403 verir; önce curl oturumu."""
    try:
        return _fetch_url_html_curl(url, referer=url)
    except Exception as curl_error:
        try:
            r = _session.get(url, timeout=35)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as req_error:
            try:
                return _fetch_url_html_browser(url, referer=url)
            except Exception as browser_error:
                raise RuntimeError(
                    f"curl: {curl_error}; requests: {req_error}; yedek: {browser_error}",
                ) from browser_error


def _fetch_source_html(now: datetime) -> str:
    errors: List[str] = []
    for url in SOURCE_URLS[:2]:
        try:
            return _fetch_url_html_curl(url, referer=SOURCE_URL)
        except Exception as e:
            errors.append(f"{url}: {e}")

    try:
        dated = f"{SOURCE_URL}?tarih={now.strftime('%Y-%m-%d')}"
        return _fetch_url_html_curl(dated, referer=SOURCE_URL)
    except Exception as e:
        errors.append(f"{SOURCE_URL}?tarih=: {e}")

    raise RuntimeError("; ".join(errors[-3:]))


def _load_today_cache(now: datetime) -> Optional[Dict[str, Any]]:
    try:
        if not CACHE_PATH.exists():
            return None
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if data.get("ok") and data.get("date") == now.strftime("%Y-%m-%d"):
            data["from_cache"] = True
            return data
    except Exception:
        return None
    return None


def _save_today_cache(data: Dict[str, Any]) -> None:
    if not data.get("ok"):
        return
    try:
        CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("Eczane cache yazılamadı: %s", e)


def _fetch_remote_pharmacies(
    remote_url: str,
    remote_token: str,
    now: datetime,
    *,
    retries: int = 3,
) -> Dict[str, Any]:
    url = (remote_url or "").strip()
    if not url:
        return _result_from_rows(now, [])

    headers = {
        "Accept": "application/json",
        "User-Agent": "BitlisBilgiBot/1.0",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if remote_token:
        headers["Authorization"] = f"Bearer {remote_token}"
        headers["X-Pharmacy-Token"] = remote_token

    data: Optional[Dict[str, Any]] = None
    last_error: Optional[Exception] = None
    sep = "&" if "?" in url else "?"
    for attempt in range(max(1, retries)):
        bust_url = f"{url}{sep}t={int(now.timestamp())}&r={attempt}"
        try:
            r = requests.get(bust_url, headers=headers, timeout=30)
            r.raise_for_status()
            payload = r.json()
            if isinstance(payload, dict):
                data = payload
                break
        except Exception as e:
            last_error = e

    if data is None:
        result = _result_from_rows(now, [])
        result["error"] = f"Uzak eczane servisi alınamadı: {last_error}"
        result["source"] = "remote_bridge"
        return result

    if not isinstance(data, dict):
        result = _result_from_rows(now, [])
        result["error"] = "Uzak eczane servisi geçersiz JSON döndürdü"
        result["source"] = "remote_bridge"
        return result

    expected_date = now.strftime("%Y-%m-%d")
    remote_date = str(data.get("date") or "").strip()
    is_stale = bool(remote_date and remote_date != expected_date)

    if not data.get("ok") or int(data.get("total") or 0) <= 0:
        result = _result_from_rows(now, [])
        result["error"] = data.get("error") or "Uzak eczane servisi boş veri döndürdü"
        result["source"] = "remote_bridge"
        return result

    if not is_stale and not is_pharmacy_cache_complete(data):
        result = _result_from_rows(now, [])
        result["error"] = (
            f"GitHub eczane cache eksik veya hatalı (total={data.get('total')}, "
            f"min={MIN_PHARMACY_TOTAL})"
        )
        result["source"] = "remote_bridge"
        result["_stale"] = True
        result["_incomplete"] = True
        result["_cache_date"] = remote_date
        return result

    data["source"] = data.get("source") or "remote_bridge"
    data["source_mode"] = data.get("source_mode") or ("remote_bridge_stale" if is_stale else "remote_bridge")
    data["remote_url"] = url
    data["_stale"] = is_stale
    return data


def _normalize_phone(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())


def _district_key(label: str) -> Optional[str]:
    low = (label or "").strip().lower()
    return DISTRICT_FROM_TEXT.get(low)


def _parse_row_district_page(text: str, district_key: str) -> Optional[Dict[str, str]]:
    """İlçe sayfası tablo satırı — metinde ilçe adı olmayabilir."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) < 15:
        return None
    phone_m = PHONE_RE.search(text)
    if not phone_m:
        return None
    phone = _normalize_phone(phone_m.group(0))
    before = text[: phone_m.start()].strip()
    label_by_key = dict(DISTRICT_ORDER)
    name = ""
    nm = re.search(r"^(.+?Eczanesi)\s+", before, re.I)
    if nm:
        name = nm.group(1).strip()
        address = before[nm.end() :].strip()
    else:
        parts = before.split(" ", 2)
        name = parts[0] if parts else "Eczane"
        address = before
    address = re.sub(r"\s*»\s*", " · ", address).strip()
    return {
        "name": name,
        "address": address,
        "phone": phone,
        "district_key": district_key,
        "district_name": label_by_key.get(district_key, district_key),
    }


def _parse_row(text: str) -> Optional[Dict[str, str]]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) < 20:
        return None

    phone_m = PHONE_RE.search(text)
    if not phone_m:
        return None
    phone = _normalize_phone(phone_m.group(0))
    before = text[: phone_m.start()].strip()

    district_label = None
    for d in ("Tatvan", "Adilcevaz", "Güroymak", "Guroymak", "Ahlat", "Hizan", "Mutki", "Merkez", "Bitlis"):
        if before.endswith(d):
            district_label = d
            before = before[: -len(d)].strip()
            break

    if not district_label:
        m = re.search(r"/\s*Bitlis\s+(\w+)\s*$", before)
        if m:
            district_label = m.group(1)
            before = before[: m.start()].strip()

    key = _district_key(district_label or "")
    if not key:
        return None

    for d in ("Tatvan", "Adilcevaz", "Güroymak", "Ahlat", "Hizan", "Mutki", "Merkez"):
        if before.endswith(d):
            before = before[: -len(d)].strip()

    name = ""
    nm = re.match(r"^(.+?Eczanesi)\s+", before, re.I)
    if nm:
        name = nm.group(1).strip()
        address = before[nm.end() :].strip()
    else:
        parts = before.split(" ", 2)
        name = parts[0] if parts else "Eczane"
        address = before

    address = re.sub(r"\s*»\s*", " · ", address).strip()
    if address.endswith("/ Bitlis"):
        address = address[: -8].strip()

    return {
        "name": name,
        "address": address,
        "phone": phone,
        "district_key": key,
        "district_name": district_label or key,
    }


def _is_period_text(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 25 or len(t) > 220:
        return False
    low = t.lower()
    return bool(re.search(r"\d{1,2}\s+\w+", t)) and (
        "gün boyu" in low
        or "sabahına" in low
        or "sabahina" in low
        or "akşamından" in low
        or "akşamindan" in low
        or "gününden" in low
        or "gununden" in low
    )


_PERIOD_LINE_RE = re.compile(
    r"(\d{1,2}\s+(?:"
    + "|".join(re.escape(m) for m in MONTHS_TR.values())
    + r")(?:\s+\w+)?\s+"
    r"(?:akşamından|akşamindan|gününden|gununden|sabahından|sabahindan|gün\s+boyu|gun\s+boyu)"
    r"[^.]*?kadar\.?)",
    re.I,
)


def _extract_period_snippet(text: str) -> str:
    """Uzun başlık metninden nöbet dönemi cümlesini ayıkla."""
    for part in re.split(r"\n", text or ""):
        part = re.sub(r"\s+", " ", part.strip())
        if _is_period_text(part):
            return part
    matches = [m.group(1).strip() for m in _PERIOD_LINE_RE.finditer(text or "")]
    valid = [m for m in matches if _is_period_text(m)]
    if valid:
        return min(valid, key=len)
    m = _PERIOD_LINE_RE.search(text or "")
    return (m.group(1).strip() if m else "")


def _extract_hurriyet_period(soup: BeautifulSoup) -> str:
    """Hürriyet — yalnızca «01 Haziran … sabahına kadar» nöbet aralığı."""
    scopes: List[str] = []
    for root in soup.select(
        ".ecz-module, .ecz-module-pharmacy-list, [class*='nobetci'], main, article",
    ):
        scopes.append(root.get_text(" ", strip=True))
    scopes.append(soup.get_text(" ", strip=True))
    for blob in scopes:
        found = _extract_period_snippet(blob)
        if found:
            return re.sub(r"\s+", " ", found).strip()
    return ""


def _period_before_table(table) -> str:
    """Tablo kapsayıcısındaki nöbet dönemi — eczaneler.gen.tr yapısı."""
    root = table.parent
    for _ in range(6):
        if root is None:
            break
        for s in root.stripped_strings:
            t = str(s).strip()
            if _is_period_text(t):
                return t
        blob = root.get_text(" ", strip=True)
        found = _extract_period_snippet(blob)
        if found and _is_period_text(found):
            return found
        root = root.parent
    return ""


def _collect_table_blocks(soup: BeautifulSoup) -> List[Tuple[str, Any]]:
    """Her nöbet tablosu + kendi dönem başlığı (sıra sayfayla aynı)."""
    blocks: List[Tuple[str, Any]] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header = rows[0].get_text(" ", strip=True).lower()
        if "eczane" not in header or "adres" not in header:
            continue
        period = _period_before_table(table)
        if period or blocks:
            blocks.append((period, table))
    return blocks


def _month_num_from_name(name: str) -> Optional[int]:
    key = (name or "").strip().lower().replace("ı", "i").replace("ş", "s")
    if key in _MONTH_NAME_TO_NUM:
        return _MONTH_NAME_TO_NUM[key]
    for full, num in _MONTH_NAME_TO_NUM.items():
        if len(full) >= 3 and key.startswith(full[:3]):
            return num
    return None


def _parse_period_start(period: str) -> Optional[Tuple[int, int]]:
    """Nöbet başlangıç günü — metnin ilk tarihi (gün, ay)."""
    m = re.search(
        r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)",
        period or "",
        re.I,
    )
    if not m:
        return None
    month = _month_num_from_name(m.group(2))
    if not month:
        return None
    return int(m.group(1)), month


def _pick_today_block_index(
    blocks: List[Tuple[str, Any]],
    now: datetime,
    *,
    for_daily_publish: bool = True,
) -> int:
    """
    Güncel nöbet tablosu.

    for_daily_publish=True (varsayılan): Bugün başlayan dönem — 12:00 paylaşımı
    için «25 Mayıs akşamından …» tablosu (Atalay vb.), dün sabaha kadar biten değil.

    for_daily_publish=False: Gece 08:00 öncesinde hâlâ sabaha kadar süren dönem.
    """
    if not blocks:
        return 0

    periods = [p for p, _ in blocks]
    today = (now.day, now.month)
    month_name = MONTHS_TR.get(now.month, "")
    today_str = f"{now.day} {month_name}"

    starting_today: List[int] = []
    for i, p in enumerate(periods):
        if _parse_period_start(p) == today:
            starting_today.append(i)

    if starting_today:
        for i in reversed(starting_today):
            pl = periods[i].lower()
            if "akşamından" in pl or "akşamindan" in pl:
                return i
        for i in reversed(starting_today):
            if "gün boyu" in periods[i].lower() or "gun boyu" in periods[i].lower():
                return i
        return starting_today[-1]

    if not for_daily_publish and now.hour < 8:
        for i, p in enumerate(periods):
            if today_str not in p:
                continue
            pl = p.lower()
            if "sabahına" not in pl and "sabahina" not in pl:
                continue
            start = _parse_period_start(p)
            if start and start != today:
                return i

    for i, p in enumerate(periods):
        if today_str in p:
            return i

    return len(blocks) - 1


def _group_by_district(rows: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    grouped: Dict[str, List[Dict[str, str]]] = {k: [] for k, _ in DISTRICT_ORDER}
    for row in rows:
        key = row.get("district_key")
        if key in grouped:
            grouped[key].append({
                "name": row["name"],
                "address": row["address"],
                "phone": row["phone"],
            })
    return grouped


def _normalized_period_text(now: datetime) -> str:
    """Nöbet aralığını bugünden yarın sabahına sabit üret."""
    start = now
    end = now + timedelta(days=1)
    return (
        f"{start.day} {MONTHS_TR[start.month]} {WEEKDAYS_TR[start.weekday()]} akşamından "
        f"{end.day} {MONTHS_TR[end.month]} {WEEKDAYS_TR[end.weekday()]} sabahına kadar."
    )


def _result_from_rows(
    now: datetime,
    rows: List[Dict[str, str]],
    period: str = "",
    *,
    no_duty_keys: Optional[set] = None,
) -> Dict[str, Any]:
    grouped = _group_by_district(rows)
    districts_out: List[Dict[str, Any]] = []
    total = 0
    empty_confirmed = no_duty_keys or set()
    for key, label in DISTRICT_ORDER:
        items = grouped.get(key, [])
        no_duty = key in empty_confirmed and not items
        districts_out.append({
            "key": key,
            "name": label,
            "pharmacies": items,
            "count": len(items),
            "no_duty": no_duty,
        })
        total += len(items)

    return {
        "ok": total > 0,
        "date": now.strftime("%Y-%m-%d"),
        "date_label": now.strftime("%d.%m.%Y"),
        "period": _normalized_period_text(now),
        "districts": districts_out,
        "total": total,
        "fetched_at": now.isoformat(timespec="seconds"),
    }


def _parse_today_rows_from_soup(
    soup: BeautifulSoup,
    now: datetime,
    *,
    for_daily_publish: bool = True,
    override_district_key: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], str]:
    blocks = _collect_table_blocks(soup)
    if not blocks:
        return [], ""

    idx = _pick_today_block_index(blocks, now, for_daily_publish=for_daily_publish)
    if idx >= len(blocks):
        idx = len(blocks) - 1
    period_text, duty_table = blocks[idx]

    label_by_key = dict(DISTRICT_ORDER)
    parsed: List[Dict[str, str]] = []
    for row in duty_table.find_all("tr")[1:]:
        cell = row.get_text(" ", strip=True)
        if override_district_key and override_district_key in _EXPECTED_DISTRICT_KEYS:
            item = _parse_row_district_page(cell, override_district_key)
        else:
            item = _parse_row(cell)
            if item and override_district_key and override_district_key in _EXPECTED_DISTRICT_KEYS:
                item["district_key"] = override_district_key
                item["district_name"] = label_by_key.get(override_district_key, override_district_key)
        if item:
            parsed.append(item)
    return parsed, period_text


def _fetch_district_page_html(url: str, session: requests.Session) -> str:
    if _github_actions_runner():
        time.sleep(2.5 + random.random())
    return _fetch_url_html(session, url)


def _fetch_hurriyet_html(url: str = HURRIYET_CITY_URL) -> str:
    """Hürriyet Bitlis nöbetçi eczane sayfası."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.hurriyet.com.tr/nobetci-eczaneler/",
        "Cache-Control": "no-cache",
    })
    r = session.get(url, timeout=40)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def _district_key_from_hurriyet_item(text: str) -> Optional[str]:
    """«Bitlis / Tatvan» satırından ilçe anahtarı."""
    m = re.search(
        r"Bitlis\s*/\s*([A-Za-zÇĞİÖŞÜçğıöşü]+)",
        text or "",
        re.I,
    )
    if not m:
        return None
    raw = m.group(1).strip().lower()
    return DISTRICT_FROM_TEXT.get(raw) or _district_key(raw)


def _parse_hurriyet_item_text(text: str, district_key: str) -> Optional[Dict[str, str]]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if "Eczanesi" not in text or not PHONE_RE.search(text):
        return None
    name_m = re.search(r"([\wğüşıöçĞÜŞİÖÇ][\wğüşıöçĞÜŞİÖÇ\s\-]{2,60}Eczanesi)", text, re.I)
    phone = _normalize_phone(PHONE_RE.search(text).group(0))
    addr_m = re.search(r"Adres:\s*(.+?)\s*Telefon:", text, re.I)
    if not name_m or not addr_m:
        return None
    label_by_key = dict(DISTRICT_ORDER)
    return {
        "name": name_m.group(1).strip(),
        "address": addr_m.group(1).strip(),
        "phone": phone,
        "district_key": district_key,
        "district_name": label_by_key.get(district_key, district_key),
    }


def _parse_hurriyet_city_page(soup: BeautifulSoup) -> Tuple[List[Dict[str, str]], str]:
    """https://www.hurriyet.com.tr/nobetci-eczaneler/bitlis/ — tüm ilçe kartları."""
    rows: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in soup.select(".ecz-module-pharmacy-item"):
        text = item.get_text(" ", strip=True)
        key = _district_key_from_hurriyet_item(text)
        if not key or key not in HURRIYET_DISTRICT_KEYS:
            continue
        parsed = _parse_hurriyet_item_text(text, key)
        if not parsed:
            continue
        sig = (key, parsed.get("phone") or "")
        if sig in seen:
            continue
        seen.add(sig)
        rows.append(parsed)

    if not rows:
        for h2 in soup.find_all("h2"):
            title = (h2.get_text(strip=True) or "").strip()
            key = _district_key(title)
            if not key or key not in HURRIYET_DISTRICT_KEYS:
                continue
            parent = h2.find_parent()
            if not parent:
                continue
            parsed = _parse_hurriyet_item_text(parent.get_text(" ", strip=True), key)
            if parsed:
                sig = (key, parsed.get("phone") or "")
                if sig not in seen:
                    seen.add(sig)
                    rows.append(parsed)

    period = _extract_hurriyet_period(soup)
    return rows, period


def _parse_hurriyet_district_page(soup: BeautifulSoup, district_key: str) -> Tuple[List[Dict[str, str]], str]:
    rows: List[Dict[str, str]] = []
    for item in soup.select(".ecz-module-pharmacy-item"):
        parsed = _parse_hurriyet_item_text(item.get_text(" ", strip=True), district_key)
        if parsed:
            rows.append(parsed)
    period = _extract_hurriyet_period(soup)
    return rows, period


def _fetch_eczaneleri_html(url: str = ECZANELERI_CITY_URL) -> str:
    """bitlis.eczaneleri.org nöbetçi eczane sayfası."""
    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    session = requests.Session()
    session.headers.update(base_headers)
    request_errors: List[str] = []
    warmups = (
        "https://www.eczaneleri.org/",
        "https://bitlis.eczaneleri.org/",
    )
    referers = (
        "https://bitlis.eczaneleri.org/",
        "https://www.eczaneleri.org/",
    )
    for ref in referers:
        try:
            for warm in warmups:
                try:
                    session.get(warm, headers={**base_headers, "Referer": warm}, timeout=20)
                except Exception:
                    pass
            r = session.get(url, headers={**base_headers, "Referer": ref}, timeout=40)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            text = (r.text or "").strip()
            if text:
                return r.text
            request_errors.append(f"bos-govde({ref})")
        except Exception as e:
            request_errors.append(f"{ref}: {e}")
    try:
        # GitHub Actions tarafında requests bazen 403 döndürüyor.
        return _fetch_url_html_browser(url, referer="https://bitlis.eczaneleri.org/")
    except Exception as e:
        raise RuntimeError("; ".join(request_errors) + f"; browser: {e}") from e


def _district_key_from_eczaneleri_label(text: str) -> Optional[str]:
    raw = (text or "").strip().lower()
    return DISTRICT_FROM_TEXT.get(raw) or _district_key(raw)


def _format_tr_phone(raw_digits: str) -> str:
    digits = re.sub(r"\D+", "", raw_digits or "")
    if len(digits) == 11 and digits.startswith("0"):
        return f"0({digits[1:4]}){digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return raw_digits.strip()


def _extract_phone_from_eczaneleri_detail(url: str) -> str:
    if not url:
        return ""
    try:
        html = _fetch_url_html_browser(url, referer=ECZANELERI_CITY_URL)
        text = re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" ", strip=True))
        m = _ECZANELERI_PHONE_RE.search(text)
        if m:
            return _format_tr_phone(m.group(1))
    except Exception:
        pass
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Referer": ECZANELERI_CITY_URL,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    for attempt in range(3):
        try:
            if attempt:
                time.sleep(0.8 * attempt + random.random() * 0.6)
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 429:
                continue
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            text = re.sub(r"\s+", " ", BeautifulSoup(r.text, "lxml").get_text(" ", strip=True))
            m = _ECZANELERI_PHONE_RE.search(text)
            if not m:
                return ""
            return _format_tr_phone(m.group(1))
        except Exception as e:
            if attempt == 2:
                logger.debug("Eczane detay telefonu alinamadi (%s): %s", url, e)
    return ""


def _normalize_pharmacy_name_key(name: str) -> str:
    text = (name or "").lower()
    text = text.replace("eczanesi", " ")
    text = re.sub(r"[^a-z0-9çğıöşü]+", "", text)
    return text


def _enrich_eczaneleri_phones_from_hurriyet(rows: List[Dict[str, str]]) -> None:
    """Eczaneleri kaynağında telefon boşsa Hürriyet'ten telefonla tamamla."""
    if not rows:
        return
    try:
        soup = BeautifulSoup(_fetch_hurriyet_html(HURRIYET_CITY_URL), "lxml")
        h_rows, _period = _parse_hurriyet_city_page(soup)
    except Exception as e:
        logger.debug("Telefon zenginlestirme atlandi (Hürriyet): %s", e)
        return
    phone_map: Dict[Tuple[str, str], str] = {}
    district_phones: Dict[str, List[str]] = {}
    for item in h_rows:
        key = str(item.get("district_key") or "")
        name_key = _normalize_pharmacy_name_key(str(item.get("name") or ""))
        phone = str(item.get("phone") or "").strip()
        if key and name_key and phone:
            phone_map[(key, name_key)] = phone
            district_phones.setdefault(key, []).append(phone)
    district_used: Dict[str, set[str]] = {}
    for item in rows:
        if str(item.get("phone") or "").strip():
            continue
        key = str(item.get("district_key") or "")
        name_key = _normalize_pharmacy_name_key(str(item.get("name") or ""))
        if not key or not name_key:
            continue
        phone = phone_map.get((key, name_key), "")
        # İsimler farklı yazılmışsa (ör. yaşam/şeker gibi güncel olmayan etiketler),
        # ilçe bazında tek telefon varsa bunu doldur.
        if not phone:
            candidates = district_phones.get(key, [])
            if len(candidates) == 1:
                phone = candidates[0]
            elif candidates:
                used = district_used.setdefault(key, set())
                free = next((p for p in candidates if p not in used), "")
                phone = free or candidates[0]
                if phone:
                    used.add(phone)
        if phone:
            item["phone"] = phone


def _parse_eczaneleri_city_page(soup: BeautifulSoup, now: datetime) -> Tuple[List[Dict[str, str]], str]:
    """bitlis.eczaneleri.org — bugün sekmesindeki eczaneleri parse et."""
    rows: List[Dict[str, str]] = []
    expected_date = now.strftime("%Y-%m-%d")
    pane = soup.select_one(f".pane-wrapper > div[data-date='{expected_date}']")
    if pane is None:
        pane = soup.select_one(".pane-wrapper > div.active")
    if pane is None:
        return [], ""

    period = ""
    alert = pane.select_one(".alert.alert-warning")
    if alert:
        period = re.sub(r"\s+", " ", alert.get_text(" ", strip=True))

    label_by_key = dict(DISTRICT_ORDER)
    for li in pane.select("ul.media-list > li.media"):
        h4 = li.select_one("h4")
        label = li.select_one("span.label.label-info")
        link = li.select_one("a[href]")
        if not h4 or not label:
            continue
        district_name = re.sub(r"\s+", " ", label.get_text(" ", strip=True))
        key = _district_key_from_eczaneleri_label(district_name)
        if not key or key not in _EXPECTED_DISTRICT_KEYS:
            continue
        name_text = re.sub(r"\s+", " ", h4.get_text(" ", strip=True))
        name = name_text.split(district_name, 1)[0].strip()
        if not name:
            continue
        body = li.select_one(".media-body")
        if not body:
            continue
        detail_url = ""
        if link:
            href = (link.get("href") or "").strip()
            if href:
                detail_url = requests.compat.urljoin(ECZANELERI_CITY_URL, href)
        phone = _extract_phone_from_eczaneleri_detail(detail_url)
        addr_lines: List[str] = []
        for content in body.contents:
            text = ""
            if isinstance(content, str):
                text = content.strip()
            else:
                tag_name = getattr(content, "name", "") or ""
                if tag_name.lower() == "br":
                    continue
                text = content.get_text(" ", strip=True)
            if not text:
                continue
            if "Eczanesi" in text and district_name in text:
                continue
            if "harita" in text.lower():
                continue
            addr_lines.append(text)
        address = re.sub(r"\s+", " ", " ".join(addr_lines)).strip(" -")
        rows.append({
            "name": name,
            "address": address,
            "phone": phone,
            "district_key": key,
            "district_name": label_by_key.get(key, district_name),
        })
    return rows, period


def _fetch_from_eczaneleri(now: datetime, *, for_daily_publish: bool = True) -> Dict[str, Any]:
    """Yalnızca bitlis.eczaneleri.org şehir sayfası."""
    result: Dict[str, Any] = _result_from_rows(now, [])
    try:
        soup = BeautifulSoup(_fetch_eczaneleri_html(ECZANELERI_CITY_URL), "lxml")
    except Exception as e:
        result["ok"] = False
        result["error"] = f"Eczaneleri sayfası alınamadı ({ECZANELERI_CITY_URL}): {e}"
        result["source"] = "bitlis.eczaneleri.org"
        logger.error("%s", result["error"])
        return result

    rows, period = _parse_eczaneleri_city_page(soup, now)
    if not rows:
        result["ok"] = False
        result["error"] = f"Eczaneleri sayfasında eczane bulunamadı ({ECZANELERI_CITY_URL})"
        result["source"] = "bitlis.eczaneleri.org"
        logger.error("%s", result["error"])
        return result
    _enrich_eczaneleri_phones_from_hurriyet(rows)

    result = _result_from_rows(now, rows, period)
    result["source"] = "bitlis.eczaneleri.org"
    result["source_mode"] = "eczaneleri_city"
    result["source_url"] = ECZANELERI_CITY_URL

    start = _parse_period_start(period or "")
    today = (now.day, now.month)
    if for_daily_publish and start and start != today:
        result["ok"] = False
        result["_stale"] = True
        result["error"] = (
            f"Eczaneleri nöbet dönemi güncel değil (period={period!r}, "
            f"beklenen={now.day} {MONTHS_TR[now.month]})."
        )
        logger.warning("%s", result["error"])
        return result

    if not is_pharmacy_cache_complete(result):
        result["ok"] = False
        result["error"] = (
            f"Eczaneleri listesi eksik (total={result.get('total')}, "
            f"min_ilce={MIN_ACTIVE_DISTRICTS - 1})"
        )
        logger.error("%s", result["error"])
    else:
        logger.info(
            "Nöbetçi eczane eczaneleri.org'dan alındı (%d eczane, %s)",
            int(result.get("total") or 0),
            ECZANELERI_CITY_URL,
        )
    return result


def _fetch_from_hurriyet(now: datetime, *, for_daily_publish: bool = True) -> Dict[str, Any]:
    """Yalnızca Hürriyet Bitlis nöbetçi eczane sayfası."""
    result: Dict[str, Any] = _result_from_rows(now, [])
    try:
        soup = BeautifulSoup(_fetch_hurriyet_html(HURRIYET_CITY_URL), "lxml")
    except Exception as e:
        result["ok"] = False
        result["error"] = f"Hürriyet sayfası alınamadı ({HURRIYET_CITY_URL}): {e}"
        result["source"] = "hurriyet.com.tr"
        logger.error("%s", result["error"])
        return result

    rows, period = _parse_hurriyet_city_page(soup)
    if not rows:
        result["ok"] = False
        result["error"] = (
            f"Hürriyet sayfasında eczane bulunamadı ({HURRIYET_CITY_URL})"
        )
        result["source"] = "hurriyet.com.tr"
        logger.error("%s", result["error"])
        return result

    result = _result_from_rows(now, rows, period)
    result["source"] = "hurriyet.com.tr"
    result["source_mode"] = "hurriyet_city"
    result["source_url"] = HURRIYET_CITY_URL

    start = _parse_period_start(period or "")
    today = (now.day, now.month)
    if for_daily_publish:
        # 12:00 paylaşımları için nöbet başlangıcı mutlaka bugün olmalı.
        if start and start != today:
            result["ok"] = False
            result["_stale"] = True
            result["error"] = (
                f"Hürriyet nöbet dönemi güncel değil (period={period!r}, "
                f"beklenen={now.day} {MONTHS_TR[now.month]})."
            )
            logger.warning("%s", result["error"])
            return result

    if not is_pharmacy_cache_complete(result):
        result["ok"] = False
        result["error"] = (
            f"Hürriyet listesi eksik (total={result.get('total')}, "
            f"min_ilce={MIN_ACTIVE_DISTRICTS})"
        )
        logger.error("%s", result["error"])
    else:
        logger.info(
            "Nöbetçi eczane Hürriyet'ten alındı (%d eczane, %s)",
            int(result.get("total") or 0),
            HURRIYET_CITY_URL,
        )
    return result


def _scrape_eczaneler_gen_tr(now: datetime, *, for_daily_publish: bool = True) -> Dict[str, Any]:
    """Mevcut eczaneler.gen.tr akisi."""
    today = now.strftime("%Y-%m-%d")
    result: Dict[str, Any] = _result_from_rows(now, [])

    try:
        soup = BeautifulSoup(_fetch_source_html(now), "lxml")
    except Exception as e:
        logger.warning("Nöbetçi eczane ana sayfası alınamadı, ilçe sayfaları deneniyor: %s", e)
        return _fetch_from_district_pages(now, for_daily_publish=for_daily_publish)

    parsed, period_text = _parse_today_rows_from_soup(
        soup, now, for_daily_publish=for_daily_publish,
    )
    if not period_text:
        result["error"] = "Tablo bulunamadı"
        return result

    result = _result_from_rows(now, parsed, period_text)
    result["source"] = "eczaneler.gen.tr"
    if result.get("ok") and not is_pharmacy_cache_complete(result):
        result = _fetch_from_district_pages(now, for_daily_publish=for_daily_publish)
    if not result.get("ok"):
        result = _fetch_from_district_pages(now, for_daily_publish=for_daily_publish)
    if result.get("ok") and not is_pharmacy_cache_complete(result):
        result["ok"] = False
        result["error"] = (
            f"Eczane listesi eksik (total={result.get('total')}, min={MIN_PHARMACY_TOTAL})"
        )
    if (
        result.get("ok")
        and is_pharmacy_cache_complete(result)
        and str(result.get("date") or "") == today
    ):
        _save_today_cache(result)
    return result


def _scrape_live_pharmacies(now: datetime, *, for_daily_publish: bool = True) -> Dict[str, Any]:
    """Canlı scrape — öncelik bitlis.eczaneleri.org, sonra Hürriyet."""
    today = now.strftime("%Y-%m-%d")
    ecz = _fetch_from_eczaneleri(now, for_daily_publish=for_daily_publish)
    if (
        ecz.get("ok")
        and is_pharmacy_cache_complete(ecz)
        and str(ecz.get("date") or "") == today
    ):
        _save_today_cache(ecz)
        return ecz

    hur = _fetch_from_hurriyet(now, for_daily_publish=for_daily_publish)
    if (
        hur.get("ok")
        and is_pharmacy_cache_complete(hur)
        and str(hur.get("date") or "") == today
    ):
        _save_today_cache(hur)
        return hur

    # Hürriyet stale/eski dönem dönerse ilçe bazlı kaynaktan toparla.
    fallback = _scrape_eczaneler_gen_tr(now, for_daily_publish=for_daily_publish)
    if (
        fallback.get("ok")
        and is_pharmacy_cache_complete(fallback)
        and str(fallback.get("date") or "") == today
    ):
        logger.warning(
            "Canlı eczane kaynağı güncel görünmedi; eczaneler.gen.tr fallback kullanıldı: %s",
            ecz.get("error") or hur.get("error") or "bilinmiyor",
        )
        _save_today_cache(fallback)
        return fallback

    cached = _load_today_cache(now)
    if cached and is_pharmacy_cache_complete(cached):
        logger.warning(
            "Hürriyet scrape başarısız; yerel bugün cache kullanılıyor: %s",
            hur.get("error") or "bilinmiyor",
        )
        return cached

    return hur


def _fetch_from_district_pages(now: datetime, *, for_daily_publish: bool = True) -> Dict[str, Any]:
    session = requests.Session()
    session.headers.update(_browser_headers())
    errors: List[str] = []
    all_rows: List[Dict[str, str]] = []
    periods: List[str] = []

    try:
        _curl_fetcher()._open_session()
    except Exception as e:
        logger.debug("İlçe scrape curl ısınma: %s", e)

    no_duty_keys: set = set()
    for key, _label in DISTRICT_ORDER:
        url = DISTRICT_SOURCE_URLS.get(key)
        if not url:
            continue
        try:
            html = _fetch_district_page_html(url, session)
            soup = BeautifulSoup(html, "lxml")
            if _text_indicates_no_duty(soup.get_text(" ", strip=True)):
                no_duty_keys.add(key)
                logger.info(
                    "İlçede nöbetçi eczane yok (resmi): %s",
                    _label,
                )
                continue
            rows, period = _parse_today_rows_from_soup(
                soup,
                now,
                for_daily_publish=for_daily_publish,
                override_district_key=key,
            )
            if period and period not in periods:
                periods.append(period)
            all_rows.extend(rows)
        except Exception as e:
            errors.append(f"{url}: {e}")

    result = _result_from_rows(
        now,
        all_rows,
        periods[0] if periods else "",
        no_duty_keys=no_duty_keys,
    )
    result["source"] = "eczaneler.gen.tr"
    result["source_mode"] = "district_pages"
    if result.get("ok") and not is_pharmacy_cache_complete(result):
        result["ok"] = False
        result["error"] = (
            f"İlçe scrape eksik (total={result.get('total')}, "
            f"min={MIN_PHARMACY_TOTAL}); "
            + ("; ".join(errors[-5:]) if errors else "tüm ilçeler alınamadı")
        )
    elif not result.get("ok"):
        result["error"] = "; ".join(errors[-3:]) or "İlçe sayfalarından eczane alınamadı"
    return result


def fetch_duty_pharmacies(
    *,
    for_daily_publish: bool = True,
    remote_url: str = "",
    remote_token: str = "",
    allow_stale_fallback: bool = False,
    github_only: bool = True,
    scrape_if_stale: bool = False,
) -> Dict[str, Any]:
    """
    Nöbetçi eczaneler.

    github_only=True (varsayılan): yalnızca GitHub raw JSON cache.
    github_only=False: eczaneler.gen.tr canlı scrape (GitHub Actions güncellemesi için).
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if github_only:
        url = (remote_url or DEFAULT_GITHUB_CACHE_URL).strip()
        if not url:
            result = _result_from_rows(now, [])
            result["error"] = "pharmacy.remote_url yapılandırılmadı"
            return result

        remote = _fetch_remote_pharmacies(url, remote_token, now)
        if not remote.get("ok"):
            logger.error("GitHub eczane cache alınamadı: %s", remote.get("error"))
            return remote

        if remote.get("_stale"):
            if allow_stale_fallback:
                logger.warning(
                    "GitHub eczane cache eski (%s) — allow_stale_fallback ile kullanılıyor.",
                    remote.get("date") or "-",
                )
                return remote
            cache_day = str(remote.get("date") or "").strip()
            if scrape_if_stale:
                logger.warning(
                    "GitHub eczane cache eski (%s) — canlı scrape deneniyor.",
                    cache_day or "-",
                )
                scraped = fetch_duty_pharmacies(
                    for_daily_publish=for_daily_publish,
                    remote_url=remote_url,
                    remote_token=remote_token,
                    allow_stale_fallback=False,
                    github_only=False,
                    scrape_if_stale=False,
                )
                if scraped.get("ok") and str(scraped.get("date") or "") == today:
                    scraped["source_mode"] = "scrape_after_stale_github"
                    _save_today_cache(scraped)
                    logger.info(
                        "Nöbetçi eczane canlı kaynaktan alındı (GitHub cache: %s).",
                        cache_day or "-",
                    )
                    return scraped
                logger.warning(
                    "Canlı eczane scrape başarısız: %s",
                    scraped.get("error") or "bilinmiyor",
                )
            result = _result_from_rows(now, [])
            result["error"] = (
                f"GitHub eczane cache güncel değil (cache: {cache_day}, bugün: {today})"
            )
            result["_stale"] = True
            result["_cache_date"] = cache_day
            logger.error(result["error"])
            return result

        _save_today_cache(remote)
        logger.info("Nöbetçi eczane GitHub cache: %s", url)
        return remote

    return _scrape_live_pharmacies(now, for_daily_publish=for_daily_publish)
