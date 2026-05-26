"""
Bitlis nöbetçi eczaneler — günlük, ilçe ilçe (eczaneler.gen.tr).
"""
from __future__ import annotations

import logging
import json
import re
from datetime import datetime
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
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
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


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_browser_headers())
    return s


def _fetch_url_html_browser(url: str, referer: str = "https://www.eczaneler.gen.tr/") -> str:
    """curl_cffi ile gerçek Chrome TLS parmak izi kullan."""
    try:
        from curl_cffi import requests as curl_requests
    except Exception as e:
        raise RuntimeError("curl_cffi yüklü değil; pip install curl_cffi") from e

    last_error: Optional[Exception] = None
    for impersonate in ("chrome124", "chrome120", "chrome110"):
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


def _fetch_url_html(session: requests.Session, url: str) -> str:
    try:
        r = session.get(url, timeout=35)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as first_error:
        try:
            return _fetch_url_html_browser(url)
        except Exception as browser_error:
            raise RuntimeError(f"{first_error}; curl_cffi: {browser_error}") from browser_error


def _fetch_source_html(now: datetime) -> str:
    session = _session()
    errors: List[str] = []

    # Ana sayfa isteği bazı sunucularda cookie/oturum oluşturuyor.
    try:
        session.get("https://www.eczaneler.gen.tr/", timeout=20)
    except Exception:
        pass

    for url in SOURCE_URLS[:2]:
        try:
            return _fetch_url_html(session, url)
        except Exception as e:
            errors.append(f"{url}: {e}")

    # Son çare: eski cache kırıcı parametreyi farklı başlıkla dene.
    try:
        return _fetch_url_html(session, f"{SOURCE_URL}?tarih={now.strftime('%Y-%m-%d')}")
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
) -> Dict[str, Any]:
    url = (remote_url or "").strip()
    if not url:
        return _result_from_rows(now, [])

    headers = {
        "Accept": "application/json",
        "User-Agent": "BitlisBilgiBot/1.0",
    }
    if remote_token:
        headers["Authorization"] = f"Bearer {remote_token}"
        headers["X-Pharmacy-Token"] = remote_token

    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        result = _result_from_rows(now, [])
        result["error"] = f"Uzak eczane servisi alınamadı: {e}"
        result["source"] = "remote_bridge"
        return result

    if not isinstance(data, dict):
        result = _result_from_rows(now, [])
        result["error"] = "Uzak eczane servisi geçersiz JSON döndürdü"
        result["source"] = "remote_bridge"
        return result

    expected_date = now.strftime("%Y-%m-%d")
    if data.get("date") != expected_date:
        result = _result_from_rows(now, [])
        result["error"] = f"Uzak eczane tarihi güncel değil: {data.get('date') or '-'}"
        result["source"] = "remote_bridge"
        return result

    if not data.get("ok") or int(data.get("total") or 0) <= 0:
        result = _result_from_rows(now, [])
        result["error"] = data.get("error") or "Uzak eczane servisi boş veri döndürdü"
        result["source"] = "remote_bridge"
        return result

    data["source"] = data.get("source") or "remote_bridge"
    data["source_mode"] = data.get("source_mode") or "remote_bridge"
    data["remote_url"] = url
    return data


def _normalize_phone(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())


def _district_key(label: str) -> Optional[str]:
    low = (label or "").strip().lower()
    return DISTRICT_FROM_TEXT.get(low)


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
    + r")[^.]*?kadar\.?)",
    re.I,
)


def _extract_period_snippet(text: str) -> str:
    """Uzun başlık metninden nöbet dönemi cümlesini ayıkla."""
    for part in re.split(r"\n", text or ""):
        part = part.strip()
        if _is_period_text(part):
            return part
    m = _PERIOD_LINE_RE.search(text or "")
    return (m.group(1).strip() if m else "")


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


def _result_from_rows(now: datetime, rows: List[Dict[str, str]], period: str = "") -> Dict[str, Any]:
    grouped = _group_by_district(rows)
    districts_out: List[Dict[str, Any]] = []
    total = 0
    for key, label in DISTRICT_ORDER:
        items = grouped.get(key, [])
        districts_out.append({
            "key": key,
            "name": label,
            "pharmacies": items,
            "count": len(items),
        })
        total += len(items)

    return {
        "ok": total > 0,
        "date": now.strftime("%Y-%m-%d"),
        "date_label": now.strftime("%d.%m.%Y"),
        "period": period,
        "districts": districts_out,
        "total": total,
        "fetched_at": now.isoformat(timespec="seconds"),
    }


def _parse_today_rows_from_soup(
    soup: BeautifulSoup,
    now: datetime,
    *,
    for_daily_publish: bool = True,
) -> Tuple[List[Dict[str, str]], str]:
    blocks = _collect_table_blocks(soup)
    if not blocks:
        return [], ""

    idx = _pick_today_block_index(blocks, now, for_daily_publish=for_daily_publish)
    if idx >= len(blocks):
        idx = len(blocks) - 1
    period_text, duty_table = blocks[idx]

    parsed: List[Dict[str, str]] = []
    for row in duty_table.find_all("tr")[1:]:
        cell = row.get_text(" ", strip=True)
        item = _parse_row(cell)
        if item:
            parsed.append(item)
    return parsed, period_text


def _fetch_from_district_pages(now: datetime, *, for_daily_publish: bool = True) -> Dict[str, Any]:
    session = _session()
    errors: List[str] = []
    all_rows: List[Dict[str, str]] = []
    periods: List[str] = []

    try:
        session.get("https://www.eczaneler.gen.tr/", timeout=20)
    except Exception:
        pass

    for key, _label in DISTRICT_ORDER:
        url = DISTRICT_SOURCE_URLS.get(key)
        if not url:
            continue
        try:
            soup = BeautifulSoup(_fetch_url_html(session, url), "lxml")
            rows, period = _parse_today_rows_from_soup(
                soup, now, for_daily_publish=for_daily_publish,
            )
            if period and period not in periods:
                periods.append(period)
            all_rows.extend(rows)
        except Exception as e:
            errors.append(f"{url}: {e}")

    result = _result_from_rows(now, all_rows, periods[0] if periods else "")
    result["source"] = "eczaneler.gen.tr"
    result["source_mode"] = "district_pages"
    if not result.get("ok"):
        result["error"] = "; ".join(errors[-3:]) or "İlçe sayfalarından eczane alınamadı"
    return result


def fetch_duty_pharmacies(
    *,
    for_daily_publish: bool = True,
    remote_url: str = "",
    remote_token: str = "",
    use_remote: bool = True,
) -> Dict[str, Any]:
    """Güncel nöbetçi eczaneler — ilçe bazlı (eczaneler.gen.tr canlı tablo)."""
    now = datetime.now()
    result: Dict[str, Any] = _result_from_rows(now, [])

    if use_remote and remote_url:
        remote = _fetch_remote_pharmacies(remote_url, remote_token, now)
        if remote.get("ok"):
            _save_today_cache(remote)
            logger.info("Nöbetçi eczane uzak servisten alındı: %s", remote_url)
            return remote
        logger.warning("Uzak eczane servisi başarısız, yerel kaynak deneniyor: %s", remote.get("error"))

    try:
        soup = BeautifulSoup(_fetch_source_html(now), "lxml")
    except Exception as e:
        logger.warning("Nöbetçi eczane ana sayfası alınamadı, ilçe sayfaları deneniyor: %s", e)
        result = _fetch_from_district_pages(now, for_daily_publish=for_daily_publish)
        if result.get("ok"):
            _save_today_cache(result)
            return result
        cached = _load_today_cache(now)
        if cached:
            logger.warning("Canlı eczane alınamadı; bugünkü eczaneler.gen.tr cache kullanılıyor.")
            return cached
        return result

    parsed, period_text = _parse_today_rows_from_soup(
        soup, now, for_daily_publish=for_daily_publish,
    )
    if not period_text:
        result["error"] = "Tablo bulunamadı"
        return result

    result = _result_from_rows(now, parsed, period_text)
    result["source"] = "eczaneler.gen.tr"
    if not result.get("ok"):
        result = _fetch_from_district_pages(now, for_daily_publish=for_daily_publish)
        if not result.get("ok"):
            result["error"] = "Eczane satırı parse edilemedi"
    if result.get("ok"):
        _save_today_cache(result)
    return result
