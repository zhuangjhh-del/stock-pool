"""Free historical board ranking from Eastmoney public end-of-day K-lines.

Board membership is the current Eastmoney classification; Eastmoney does not
publish a free dated membership archive.  This module deliberately keeps that
limitation in the returned metadata so a backtest is never presented as a
point-in-time constituent reconstruction.
"""
from __future__ import annotations

import json
import time
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from eastmoney_boards import _is_limit_up, _request, _symbol

KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def _get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """Fetch a public endpoint conservatively; transient disconnects are common."""
    request = Request(f"{url}?{urlencode(params)}", headers={"User-Agent": "stock-pool-research/1.0"})
    last_error: Exception | None = None
    for delay in (0, 2, 6, 15):
        if delay:
            time.sleep(delay)
        try:
            with urlopen(request, timeout=30) as response:  # nosec: fixed HTTPS endpoint
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # the public Eastmoney edge occasionally closes keep-alive requests
            last_error = exc
    raise RuntimeError(f"东方财富历史板块请求连续失败：{last_error}")


def board_catalog() -> list[dict[str, str]]:
    payload = _request({"pn": 1, "pz": 200, "po": 1, "np": 1, "fltt": 2, "fid": "f3", "fs": "m:90+t:2", "fields": "f12,f14"})
    return [{"board_code": str(row["f12"]), "name": str(row.get("f14") or "")} for row in payload.get("data", {}).get("diff", [])]


def board_changes(catalog: list[dict[str, str]], dates: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Return the top five historical industry boards for every requested date."""
    if not dates:
        return {}
    begin, end = min(dates).replace("-", ""), max(dates).replace("-", "")
    by_day = {day: [] for day in dates}
    for board in catalog:
        payload = _get(KLINE_URL, {"secid": f"90.{board['board_code']}", "klt": 101, "fqt": 0, "beg": begin, "end": end, "lmt": 1000, "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"})
        for line in payload.get("data", {}).get("klines", []) or []:
            values = line.split(",")
            if len(values) >= 9 and values[0] in by_day:
                by_day[values[0]].append({**board, "pct_chg": float(values[8] or 0)})
        time.sleep(0.45)
    return {day: sorted(items, key=lambda item: item["pct_chg"], reverse=True)[:5] for day, items in by_day.items()}


def current_members(board_code: str) -> list[dict[str, Any]]:
    """Current constituent list, intentionally used for the documented free fallback."""
    return _request({"pn": 1, "pz": 5000, "po": 1, "np": 1, "fltt": 2, "fid": "f3", "fs": f"b:{board_code}+f:!50", "fields": "f12,f13,f14"}).get("data", {}).get("diff", [])


def historical_hot_sectors(day: date, ranked_boards: list[dict[str, Any]], daily_rows: dict[str, dict], daily_basic: dict[str, dict], history: dict[str, list[dict]], unlock_codes: set[str]) -> dict:
    """Select mainlines and stocks using historical EOD bars and current members."""
    from technical_filters import evaluate

    output, candidates = [], []
    for board in ranked_boards:
        members = current_members(board["board_code"])
        limit_up = 0
        for member in members:
            code = _symbol(member)
            row = daily_rows.get(code)
            if row and _is_limit_up({"f12": str(member.get("f12", "")), "f14": str(member.get("f14", "")), "f3": row.get("pct_chg", 0)}):
                limit_up += 1
        output.append({**board, "limit_up_count": limit_up})
        if limit_up >= 3:
            for member in members:
                code = _symbol(member)
                bar, basic = daily_rows.get(code), daily_basic.get(code)
                if not bar or not basic:
                    continue
                bars = history.get(code, [])
                prior_volumes = [float(x.get("vol") or 0) for x in bars[-6:-1]]
                volume_ratio = float(bar.get("vol") or 0) / (sum(prior_volumes) / len(prior_volumes)) if prior_volumes and sum(prior_volumes) else 0
                pre_close = float(bar.get("pre_close") or 0)
                amplitude = (float(bar["high"]) - float(bar["low"])) / pre_close * 100 if pre_close else 0
                candidates.append({"code": code, "name": str(member.get("f14") or ""), "pct_chg": float(bar.get("pct_chg") or 0), "turnover": float(basic.get("turnover_rate") or 0), "volume_ratio": volume_ratio, "market_cap": float(basic.get("total_mv") or 0) * 10000, "amplitude": amplitude, "board": board["name"]})
    mainlines = [item for item in output if item["limit_up_count"] >= 3][:2]
    allowed = {item["board_code"] for item in mainlines}
    selected, seen = [], set()
    for candidate in candidates:
        if candidate["board"] not in {item["name"] for item in mainlines} or candidate["code"] in seen:
            continue
        seen.add(candidate["code"])
        passed, reason = evaluate(candidate, history.get(candidate["code"], []), unlock_codes)
        if passed:
            selected.append({"ts_code": candidate["code"], "name": candidate["name"], "board": candidate["board"], "pct_chg": round(candidate["pct_chg"], 2), "reason": reason})
    return {"status": "READY", "rule": "行业板块历史涨幅前5；板块内涨停个股不少于3只", "top_boards": output, "mainlines": mainlines, "selected_stocks": selected, "reason": "历史板块涨幅按当日收盘数据；板块成分按当前东方财富归属复算；量比为收盘相对成交量代理值", "historical_method": "free-current-membership"}
