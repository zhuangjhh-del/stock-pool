"""Low-frequency Eastmoney board scanner for the daily GitHub Action."""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://push2.eastmoney.com/api/qt/clist/get"
MIN_INTERVAL_SECONDS = 1.2
_last_request_at = 0.0


def _request(params: dict[str, Any]) -> dict[str, Any]:
    global _last_request_at
    wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    request = Request(f"{BASE_URL}?{urlencode(params)}", headers={"User-Agent": "stock-pool-research/1.0"})
    with urlopen(request, timeout=20) as response:  # nosec: fixed HTTPS endpoint
        payload = json.loads(response.read().decode("utf-8"))
    _last_request_at = time.monotonic()
    return payload


def _is_limit_up(row: dict[str, Any]) -> bool:
    code, name = str(row.get("f12", "")), str(row.get("f14", ""))
    pct = float(row.get("f3") or 0)
    if "ST" in name.upper():
        return pct >= 4.9
    if code.startswith(("300", "688")):
        return pct >= 19.8
    if code.startswith(("4", "8")):
        return pct >= 29.5
    return pct >= 9.8


def scan_hot_sectors() -> dict[str, Any]:
    """Return the top five industry boards and select up to two confirmed leaders."""
    ranking = _request({"pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "fid": "f3", "fs": "m:90+t:2", "fields": "f12,f14,f3,f2,f104,f105,f128"})
    boards = ranking.get("data", {}).get("diff", [])
    if not boards:
        raise RuntimeError("东方财富未返回行业板块涨幅榜")
    output = []
    for board in boards:
        code = str(board["f12"])
        members = _request({"pn": 1, "pz": 5000, "po": 1, "np": 1, "fltt": 2, "fid": "f3", "fs": f"b:{code}+f:!50", "fields": "f12,f14,f2,f3,f18"}).get("data", {}).get("diff", [])
        limit_up = sum(_is_limit_up(stock) for stock in members)
        output.append({"board_code": code, "name": board.get("f14"), "pct_chg": round(float(board.get("f3") or 0), 2), "leader": board.get("f128") or "—", "up_count": int(board.get("f104") or 0), "down_count": int(board.get("f105") or 0), "limit_up_count": limit_up})
    qualified = [item for item in output if item["limit_up_count"] >= 3]
    return {"status": "READY", "rule": "行业板块涨幅前5；板块内涨停个股不少于3只", "top_boards": output, "mainlines": qualified[:2], "reason": "按板块涨幅排序，并以涨停数量确认资金共识"}
