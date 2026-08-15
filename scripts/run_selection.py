#!/usr/bin/env python3
"""Run the free, end-of-day stock-pool update and publish static JSON."""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DATA = DOCS / "data"
RUNS = DATA / "runs"
LOGS = ROOT / "logs"
CONFIG = ROOT / "config" / "strategy.yaml"
NAMES = ROOT / "config" / "stock_names.csv"
TZ = ZoneInfo("Asia/Shanghai")
# Tushare writes the daily bar after the close and its advertised window can extend
# beyond 15:15.  This covers that window without publishing stale prior-day data.
RETRIES = (0, 300, 900, 1800)  # first try, then 5, 15 and 30 minutes


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_config() -> dict:
    import yaml
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def stock_names() -> dict[str, str]:
    if not NAMES.exists():
        return {}
    lines = NAMES.read_text(encoding="utf-8-sig").splitlines()[1:]
    return dict(line.split(",", 1) for line in lines if "," in line)


def is_trade_day(today: date, cfg: dict) -> bool:
    value = today.isoformat()
    market = cfg["market"]
    if value in market.get("forced_closed_dates", []):
        return False
    if value in market.get("forced_open_dates", []):
        return True
    from chinese_calendar import is_workday
    return is_workday(today)


def fetch_daily(trade_date: str) -> list[dict]:
    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("未设置 TUSHARE_TOKEN GitHub Secret")
    pro = ts.pro_api(token)
    frame = pro.daily(trade_date=trade_date)
    if frame.empty:
        raise RuntimeError("数据源尚未返回当日日线数据")
    return frame.to_dict(orient="records")


def select(rows: list[dict], cfg: dict) -> list[dict]:
    f = cfg["strategy"]["filters"]
    prefixes = tuple(cfg["strategy"].get("exclude_prefixes", []))
    names = stock_names()
    selected = []
    for row in rows:
        code = str(row["ts_code"])
        if prefixes and code.startswith(prefixes):
            continue
        high, low, close = (float(row[k]) for k in ("high", "low", "close"))
        amount, pct = float(row["amount"]), float(row["pct_chg"])
        position = 1.0 if high == low else (close - low) / (high - low)
        if not (close >= f["min_close"] and amount >= f["min_amount_thousand_yuan"]
                and f["min_pct_chg"] <= pct <= f["max_pct_chg"]
                and position >= f["min_price_position"]):
            continue
        selected.append({
            "ts_code": code, "name": names.get(code, "—"), "close": close,
            "pct_chg": round(pct, 2), "amount_yuan": round(amount * 1000),
            "price_position": round(position, 3),
            "reason": "满足价格、成交额、涨幅和日内强度阈值",
        })
    selected.sort(key=lambda item: (item["pct_chg"], item["amount_yuan"]), reverse=True)
    return selected[: int(cfg["strategy"]["max_results"])]


def execute() -> int:
    cfg = load_config()
    now = datetime.now(TZ)
    run_id = now.strftime("%Y-%m-%d")
    metadata = {
        "run_id": run_id, "updated_at": now.isoformat(), "timezone": "Asia/Shanghai",
        "strategy": cfg["strategy"], "source": "Tushare A股日线（盘后数据）",
    }
    if not is_trade_day(now.date(), cfg):
        payload = {**metadata, "status": "SKIPPED", "reason": "非交易日、节假日或配置的休市日", "stocks": []}
        write_json(RUNS / f"{run_id}.json", payload)
        write_json(DATA / "latest.json", payload)
        return 0
    error = None
    for delay in RETRIES:
        if delay:
            time.sleep(delay)
        try:
            rows = fetch_daily(now.strftime("%Y%m%d"))
            payload = {**metadata, "status": "SUCCESS", "total_scanned": len(rows), "stocks": select(rows, cfg)}
            write_json(RUNS / f"{run_id}.json", payload)
            write_json(DATA / "latest.json", payload)
            refresh_index()
            return 0
        except Exception as exc:  # retries intentionally cover network and delayed data ingestion
            error = str(exc)
            logging.exception("selection attempt failed")
    payload = {**metadata, "status": "FAILED", "reason": error, "stocks": []}
    write_json(RUNS / f"{run_id}.json", payload)
    write_json(DATA / "latest.json", payload)
    return 1


def refresh_index() -> None:
    history = []
    for path in sorted(RUNS.glob("*.json"), reverse=True):
        item = json.loads(path.read_text(encoding="utf-8"))
        history.append({"run_id": item["run_id"], "status": item["status"], "updated_at": item["updated_at"], "count": len(item.get("stocks", []))})
    write_json(DATA / "history.json", history[:365])


if __name__ == "__main__":
    LOGS.mkdir(exist_ok=True)
    logging.basicConfig(filename=LOGS / "selection.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(execute())
