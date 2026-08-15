#!/usr/bin/env python3
"""Run the free, end-of-day stock-pool update and publish static JSON."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
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
INDEXES = {"000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指"}


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


def fetch_daily(trade_date: str) -> tuple[list[dict], object]:
    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("未设置 TUSHARE_TOKEN GitHub Secret")
    pro = ts.pro_api(token)
    frame = pro.daily(trade_date=trade_date)
    if frame.empty:
        raise RuntimeError("数据源尚未返回当日日线数据")
    return frame.to_dict(orient="records"), pro


def market_weather(rows: list[dict], pro: object, today: date) -> dict:
    rising = sum(float(row["pct_chg"]) > 0 for row in rows)
    falling = sum(float(row["pct_chg"]) < 0 for row in rows)
    ratio = None if falling == 0 else round(rising / falling, 2)
    try:
        values = []
        start, end = (today - timedelta(days=45)).strftime("%Y%m%d"), today.strftime("%Y%m%d")
        for code, name in INDEXES.items():
            frame = pro.index_daily(ts_code=code, start_date=start, end_date=end)
            if len(frame) < 20:
                raise RuntimeError(f"{name} 的有效日线不足 20 个交易日")
            close, ma20 = float(frame.iloc[0]["close"]), float(frame.head(20)["close"].mean())
            values.append({"code": code, "name": name, "close": round(close, 2), "ma20": round(ma20, 2), "above_ma20": close >= ma20})
        above_all, below_all = all(i["above_ma20"] for i in values), all(not i["above_ma20"] for i in values)
        if above_all and ratio is not None and ratio > 2:
            label, reason = "可操作", "三大指数均站上20日均线，且涨跌比大于2:1"
        elif below_all and ratio is not None and ratio < 1:
            label, reason = "空仓", "三大指数均跌破20日均线，且涨跌比小于1:1"
        else:
            label, reason = "谨慎", "指数趋势或涨跌比未达到“可操作”或“空仓”条件"
        return {"status": "READY", "label": label, "reason": reason, "rising": rising, "falling": falling, "ratio": ratio, "indexes": values}
    except Exception as exc:
        return {"status": "UNAVAILABLE", "label": "数据不足", "reason": f"无法取得三大指数20日均线数据：{exc}", "rising": rising, "falling": falling, "ratio": ratio, "indexes": []}


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
        payload = {**metadata, "status": "SKIPPED", "reason": "非交易日、节假日或配置的休市日", "market_weather": {"status": "CLOSED", "label": "休市", "reason": "非交易日、节假日或配置的休市日", "indexes": []}, "stocks": []}
        write_json(RUNS / f"{run_id}.json", payload)
        write_json(DATA / "latest.json", payload)
        refresh_index()
        return 0
    error = None
    for delay in RETRIES:
        if delay:
            time.sleep(delay)
        try:
            rows, pro = fetch_daily(now.strftime("%Y%m%d"))
            payload = {**metadata, "status": "SUCCESS", "total_scanned": len(rows), "market_weather": market_weather(rows, pro, now.date()), "stocks": select(rows, cfg)}
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
    refresh_index()
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
