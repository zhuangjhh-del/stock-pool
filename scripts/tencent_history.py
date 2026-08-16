"""Tencent daily K-line adapter used for technical indicators of candidates."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen


URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def _symbol(code: str) -> str:
    number, market = code.split(".", 1)
    return ("sh" if market == "SH" else "sz") + number


def _one(code: str, today: date) -> tuple[str, list[dict]]:
    params = {"param": f"{_symbol(code)},day,{(today - timedelta(days=120)).isoformat()},{today.isoformat()},150,qfq"}
    request = Request(f"{URL}?{urlencode(params)}", headers={"User-Agent": "Mozilla/5.0 stock-pool-research"})
    with urlopen(request, timeout=20) as response:  # nosec: fixed HTTPS source
        data = json.loads(response.read().decode("utf-8"))
    body = data.get("data", {}).get(_symbol(code), {})
    lines = body.get("qfqday") or body.get("day") or []
    rows, previous = [], None
    for line in lines:
        if len(line) < 6:
            continue
        rows.append({"trade_date": str(line[0]).replace("-", ""), "open": line[1], "close": line[2], "high": line[3], "low": line[4], "vol": line[5], "pre_close": previous or line[2]})
        previous = line[2]
    return code, rows


def candidate_kline(codes: set[str], today: date) -> dict[str, list[dict]]:
    """Fetch up to 30 candidate histories concurrently from Tencent."""
    output: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_one, code, today) for code in list(codes)[:30]]
        for future in as_completed(futures):
            try:
                code, rows = future.result()
                if rows:
                    output[code] = rows
            except Exception:
                continue
    return output
