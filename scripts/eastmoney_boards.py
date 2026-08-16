"""Low-frequency Eastmoney board scanner for the daily GitHub Action."""
from __future__ import annotations

import json
import time
from typing import Any
from datetime import date, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://push2.eastmoney.com/api/qt/clist/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
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


def _symbol(row: dict[str, Any]) -> str:
    code = str(row.get("f12", ""))
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SH" if str(row.get("f13")) == "1" else f"{code}.SZ"


def future_unlock_codes(today: date, horizon_days: int = 90) -> set[str]:
    """One paged Eastmoney disclosure query for the future unlock exclusion list."""
    end = today + timedelta(days=horizon_days)
    params = {"reportName": "RPT_LIFT_STOCK", "columns": "SECURITY_CODE,FREE_DATE", "filter": f"(FREE_DATE>='{today.isoformat()}')(FREE_DATE<='{end.isoformat()}')", "sortColumns": "FREE_DATE", "sortTypes": "1", "pageNumber": 1, "pageSize": 5000, "source": "WEB", "client": "WEB"}
    url = f"https://datacenter-web.eastmoney.com/api/data/v1/get?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "stock-pool-research/1.0"})
    with urlopen(request, timeout=20) as response:  # nosec: fixed HTTPS endpoint
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("result", {}).get("data", []) or []
    return {str(row["SECURITY_CODE"]) for row in rows if row.get("SECURITY_CODE")}


def candidate_kline(codes: set[str], today: date) -> dict[str, list[dict]]:
    """Low-volume, timeout-bounded historical K-lines for hot-board candidates."""
    output: dict[str, list[dict]] = {}
    begin = (today - timedelta(days=110)).strftime("%Y%m%d")
    for code in list(codes)[:30]:
        secid = ("1." if code.endswith(".SH") else "0.") + code.split(".")[0]
        try:
            payload = _request_kline({"secid": secid, "klt": 101, "fqt": 0, "beg": begin, "end": today.strftime("%Y%m%d"), "lmt": 150, "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"})
            rows = []
            previous = None
            for line in payload.get("data", {}).get("klines", []) or []:
                p = line.split(",")
                if len(p) < 6: continue
                rows.append({"trade_date": p[0].replace("-", ""), "open": p[1], "close": p[2], "high": p[3], "low": p[4], "vol": p[5], "pre_close": previous or p[2]})
                previous = p[2]
            output[code] = rows
        except Exception:
            continue
    return output


def _request_kline(params: dict[str, Any]) -> dict[str, Any]:
    request = Request(f"{KLINE_URL}?{urlencode(params)}", headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    with urlopen(request, timeout=25) as response:  # nosec: fixed HTTPS endpoint
        return json.loads(response.read().decode("utf-8"))


def scan_hot_sectors() -> dict[str, Any]:
    """Return the top five industry boards and select up to two confirmed leaders."""
    ranking = _request({"pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "fid": "f3", "fs": "m:90+t:2", "fields": "f12,f14,f3,f2,f104,f105,f128"})
    boards = ranking.get("data", {}).get("diff", [])
    if not boards:
        raise RuntimeError("东方财富未返回行业板块涨幅榜")
    output, candidates = [], []
    for board in boards:
        code = str(board["f12"])
        members = _request({"pn": 1, "pz": 5000, "po": 1, "np": 1, "fltt": 2, "fid": "f3", "fs": f"b:{code}+f:!50", "fields": "f2,f3,f7,f8,f10,f12,f13,f14,f20,f18"}).get("data", {}).get("diff", [])
        limit_up = sum(_is_limit_up(stock) for stock in members)
        item = {"board_code": code, "name": board.get("f14"), "pct_chg": round(float(board.get("f3") or 0), 2), "leader": board.get("f128") or "—", "up_count": int(board.get("f104") or 0), "down_count": int(board.get("f105") or 0), "limit_up_count": limit_up}
        output.append(item)
        item["members"] = members
    qualified = [item for item in output if item["limit_up_count"] >= 3]
    mainlines = qualified[:2]
    mainline_codes = {item["board_code"] for item in mainlines}
    for board in output:
        if board["board_code"] in mainline_codes:
            for row in board.pop("members"):
                candidates.append({"code": _symbol(row), "name": str(row.get("f14") or ""), "pct_chg": float(row.get("f3") or 0), "turnover": float(row.get("f8") or 0), "volume_ratio": float(row.get("f10") or 0), "market_cap": float(row.get("f20") or 0), "amplitude": float(row.get("f7") or 0), "board": board["name"]})
        else:
            board.pop("members")
    return {"status": "READY", "rule": "行业板块涨幅前5；板块内涨停个股不少于3只", "top_boards": output, "mainlines": mainlines, "candidates": candidates, "reason": "按板块涨幅排序，并以涨停数量确认资金共识"}
