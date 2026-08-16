"""Best-effort A-share real-time quote adapter for the cloud job.

The Sina market-centre endpoint is deliberately isolated here so the selector
can fail over without coupling itself to a single vendor.  It is public quote
data for research display, not a licensed commercial market-data feed.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
HEADERS = {"Referer": "https://vip.stock.finance.sina.com.cn/", "User-Agent": "Mozilla/5.0 stock-pool-research"}
NODES = ("sh_a", "sz_a")
PAGE_SIZE = 80
MAX_PAGES_PER_NODE = 70


def _get(node: str, page: int) -> list[dict[str, Any]]:
    params = {"page": page, "num": PAGE_SIZE, "sort": "symbol", "asc": 1, "node": node}
    request = Request(f"{URL}?{urlencode(params)}", headers=HEADERS)
    with urlopen(request, timeout=15) as response:  # nosec: fixed HTTPS source
        body = response.read().decode("utf-8", errors="replace").strip()
    # The endpoint normally returns a JSON array, but occasionally wraps it in
    # a JavaScript assignment.  Accept both representations.
    if "=" in body and not body.startswith("["):
        body = body.split("=", 1)[1].rstrip(";")
    data = json.loads(body)
    return data if isinstance(data, list) else []


def _code(item: dict[str, Any]) -> str:
    code = str(item.get("code") or item.get("symbol") or "").replace("sh", "").replace("sz", "")
    if len(code) != 6 or not code.isdigit():
        return ""
    return f"{code}.SH" if str(item.get("symbol", "")).startswith("sh") or code.startswith("6") else f"{code}.SZ"


def _number(value: Any) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def fetch_all() -> list[dict[str, Any]]:
    """Return a bounded, parallel full-market snapshot in selector format."""
    jobs = [(node, page) for node in NODES for page in range(1, MAX_PAGES_PER_NODE + 1)]
    raw: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_get, node, page) for node, page in jobs]
        for future in as_completed(futures):
            try:
                raw.extend(future.result())
            except Exception:
                # A partial snapshot is not acceptable: the caller will use a
                # different source when the market coverage is too small.
                continue
    output, seen = [], set()
    for item in raw:
        code = _code(item)
        if not code or code in seen:
            continue
        seen.add(code)
        close = _number(item.get("trade"))
        if close <= 0:
            continue
        output.append({
            "ts_code": code,
            "name": str(item.get("name") or ""),
            "high": _number(item.get("high")),
            "low": _number(item.get("low")),
            "close": close,
            "amount": _number(item.get("amount")) / 1000,
            "pct_chg": _number(item.get("changepercent")),
        })
    if len(output) < 2500:
        raise RuntimeError(f"新浪行情覆盖不足（仅 {len(output)} 只）")
    return output
