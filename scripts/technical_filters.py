"""Pure technical filters used after a stock has entered a hot-sector candidate pool."""
from __future__ import annotations

from statistics import mean


def _ema(values: list[float], period: int) -> list[float]:
    factor, output = 2 / (period + 1), [values[0]]
    for value in values[1:]:
        output.append(value * factor + output[-1] * (1 - factor))
    return output


def _macd_cross(closes: list[float]) -> bool:
    if len(closes) < 35:
        return False
    dif = [a - b for a, b in zip(_ema(closes, 12), _ema(closes, 26))]
    dea = _ema(dif, 9)
    return dif[-2] <= dea[-2] and dif[-1] > dea[-1]


def _kdj_cross(rows: list[dict]) -> bool:
    if len(rows) < 10:
        return False
    k = d = 50.0
    series = []
    for index in range(8, len(rows)):
        window = rows[index - 8:index + 1]
        high, low = max(float(x["high"]) for x in window), min(float(x["low"]) for x in window)
        rsv = 50 if high == low else 100 * (float(rows[index]["close"]) - low) / (high - low)
        k, d = (2 * k + rsv) / 3, (2 * d + k) / 3
        series.append((k, d))
    return len(series) >= 2 and series[-2][0] <= series[-2][1] and series[-1][0] > series[-1][1]


def _morning_star(rows: list[dict]) -> bool:
    if len(rows) < 3:
        return False
    first, second, third = rows[-3:]
    first_body = abs(float(first["close"]) - float(first["open"]))
    second_body = abs(float(second["close"]) - float(second["open"]))
    midpoint = (float(first["open"]) + float(first["close"])) / 2
    return float(first["close"]) < float(first["open"]) and second_body < first_body * .45 and float(third["close"]) > float(third["open"]) and float(third["close"]) > midpoint


def _three_white_soldiers(rows: list[dict]) -> bool:
    if len(rows) < 3:
        return False
    a, b, c = rows[-3:]
    return all(float(x["close"]) > float(x["open"]) for x in (a, b, c)) and float(a["close"]) < float(b["close"]) < float(c["close"])


def _limit_pct(code: str, name: str) -> float:
    if "ST" in name.upper():
        return .049
    if code.startswith(("300", "688")):
        return .198
    if code.startswith(("4", "8")):
        return .295
    return .098


def evaluate(candidate: dict, history: list[dict], unlock_codes: set[str]) -> tuple[bool, str]:
    """Return whether all requested rules pass and a human-readable selection reason."""
    code, name = candidate["code"], candidate["name"]
    pct, turnover, volume_ratio = float(candidate["pct_chg"]), float(candidate["turnover"]), float(candidate["volume_ratio"])
    market_cap, amplitude = float(candidate["market_cap"]), float(candidate["amplitude"])
    if not (-7 <= pct <= 9 and 3 <= turnover <= 25 and volume_ratio > 1 and market_cap > 5_000_000_000 and amplitude > 2):
        return False, "未通过当日流动性/波动条件"
    if "ST" in name.upper() or code in unlock_codes or len(history) < 60:
        return False, "ST、近90日解禁或历史数据不足"
    closes = [float(row["close"]) for row in history]
    ma5, ma20, ma60 = mean(closes[-5:]), mean(closes[-20:]), mean(closes[-60:])
    prior_ma20 = mean(closes[-21:-1])
    if not (closes[-1] > ma60 and ma5 > ma20 > ma60 and ma20 > prior_ma20):
        return False, "未通过均线多头或MA斜率条件"
    near_limit_up = any((float(row["close"]) / float(row["pre_close"]) - 1) >= _limit_pct(code, name) for row in history[-20:] if float(row["pre_close"]) > 0)
    if not near_limit_up:
        return False, "近20日无涨停"
    signals = [label for label, passed in [("MACD金叉", _macd_cross(closes)), ("KDJ金叉", _kdj_cross(history)), ("早晨之星", _morning_star(history)), ("红三兵", _three_white_soldiers(history))] if passed]
    if not signals:
        return False, "未出现指定技术信号"
    return True, f"热门板块内；MA5>MA20>MA60且MA20上行；近20日涨停；{'、'.join(signals)}"
