from __future__ import annotations

from datetime import date, datetime, timedelta
from io import StringIO
import html
import json
from pathlib import Path
import re
import sys

import pandas as pd
import requests
import yfinance as yf


VOL = {
    "vix": ("^VIX", "VIX", "标普500"),
    "vxn": ("^VXN", "VXN", "纳斯达克100"),
    "vix3m": ("^VIX3M", "VIX3M", "标普500"),
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
}


def get(url: str) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response


def close_series(symbol: str) -> pd.Series:
    frame = yf.Ticker(symbol).history(
        period="5y", interval="1d", auto_adjust=False, actions=False
    )
    if frame.empty or "Close" not in frame:
        raise RuntimeError(f"No price data returned for {symbol}")
    series = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if series.empty:
        raise RuntimeError(f"No valid closes returned for {symbol}")
    index = pd.to_datetime(series.index)
    try:
        index = index.tz_localize(None)
    except TypeError:
        pass
    series.index = index
    return series.sort_index()


def percentile(series: pd.Series, years: int) -> float | None:
    window = series[series.index >= series.index.max() - pd.DateOffset(years=years)]
    if window.empty:
        return None
    return round(float((window <= float(series.iloc[-1])).mean() * 100), 2)


def positive_number(value) -> float | None:
    try:
        number = float(value)
        return round(number, 4) if pd.notna(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def volatility_signal(label: str, rank: float | None) -> tuple[str, str]:
    if rank is None:
        return "中立", f"{label}缺少过去3年分位数据"
    if rank >= 75:
        return "偏买", f"{label}位于过去3年高位，恐慌偏高，反向信号偏买"
    if rank <= 25:
        return "偏卖", f"{label}位于过去3年低位，市场平静，反向信号偏卖"
    return "中立", f"{label}位于过去3年中性区间"


def put_call_signal(value: float | None) -> tuple[str, str]:
    if value is None:
        return "中立", "Equity Put/Call缺少数据"
    if value >= 0.90:
        return "偏买", "Put/Call偏高，防御情绪较重，反向信号偏买"
    if value <= 0.55:
        return "偏卖", "Put/Call偏低，情绪偏乐观，反向信号偏卖"
    return "中立", "Put/Call处于中性区间"


def baa_signal(value: float | None) -> tuple[str, str]:
    if value is None:
        return "中立", "Baa信用利差缺少数据"
    if value >= 2.50:
        return "偏买", "信用利差偏高，风险溢价较大，反向信号偏买"
    if value <= 1.50:
        return "偏卖", "信用利差较低，信用环境宽松，反向信号偏卖"
    return "中立", "信用利差处于中性区间"


def fear_greed_signal(value: float | None) -> tuple[str, str]:
    if value is None:
        return "中立", "恐惧贪婪指数缺少数据"
    if value <= 25:
        return "偏买", "处于极度恐惧区间，反向信号偏买"
    if value >= 75:
        return "偏卖", "处于极度贪婪区间，反向信号偏卖"
    return "中立", "恐惧贪婪指数处于中性区间"


def forward_pe_signal(value: float | None, market: str) -> tuple[str, str]:
    if value is None:
        return "中立", f"{market} Forward PE缺少数据"
    low, high = (17.0, 22.0) if market == "标普500" else (22.0, 30.0)
    if value <= low:
        return "偏买", f"{market} Forward PE偏低，估值相对便宜"
    if value >= high:
        return "偏卖", f"{market} Forward PE偏高，估值相对偏贵"
    return "中立", f"{market} Forward PE处于中性区间"


def fetch_put_call() -> dict:
    errors = []
    for days_back in range(11):
        data_date = date.today() - timedelta(days=days_back)
        url = f"https://www.cboe.com/us/options/market_statistics/daily/?dt={data_date.isoformat()}"
        try:
            text = html.unescape(re.sub(r"<[^>]+>", " ", get(url).text))
            text = re.sub(r"\s+", " ", text)
            match = re.search(
                r"EQUITY PUT/CALL RATIO\s+([0-9]+(?:\.[0-9]+)?)", text, re.I
            )
            if match:
                value = round(float(match.group(1)), 4)
                signal, explanation = put_call_signal(value)
                return {
                    "value": value, "date": data_date.isoformat(), "source": "Cboe",
                    "signal": signal, "explanation": explanation,
                }
            errors.append(f"{data_date}: ratio not found")
        except Exception as exc:
            errors.append(f"{data_date}: {exc}")
    raise RuntimeError(" | ".join(errors[-3:]))


def fetch_baa() -> dict:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAA10Y"
    frame = pd.read_csv(StringIO(get(url).text))
    frame["BAA10Y"] = pd.to_numeric(frame["BAA10Y"], errors="coerce")
    frame = frame.dropna(subset=["BAA10Y"])
    if frame.empty:
        raise RuntimeError("No FRED BAA10Y data returned")
    row = frame.iloc[-1]
    date_column = "observation_date" if "observation_date" in frame else frame.columns[0]
    value = round(float(row["BAA10Y"]), 4)
    signal, explanation = baa_signal(value)
    return {
        "value": value, "unit": "percentage_points", "date": str(row[date_column]),
        "source": "FRED BAA10Y", "signal": signal, "explanation": explanation,
    }


def fetch_fear_greed() -> dict:
    item = get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata").json()["fear_and_greed"]
    timestamp = item.get("timestamp")
    data_date = (
        datetime.fromtimestamp(float(timestamp) / 1000).date().isoformat()
        if timestamp else date.today().isoformat()
    )
    value = round(float(item["score"]), 2)
    signal, explanation = fear_greed_signal(value)
    return {
        "value": value, "rating": str(item.get("rating", "")), "date": data_date,
        "source": "CNN Fear & Greed", "signal": signal, "explanation": explanation,
    }


def fetch_pe(index_symbol: str, etf_symbol: str) -> dict:
    partial = None
    errors = []
    for symbol, proxy in [(index_symbol, False), (etf_symbol, True)]:
        try:
            ticker = yf.Ticker(symbol)
            try:
                info = ticker.get_info()
            except Exception:
                info = ticker.info
            result = {
                "trailing_pe": positive_number(info.get("trailingPE")),
                "forward_pe": positive_number(info.get("forwardPE")),
                "source_symbol": symbol,
                "is_etf_proxy": proxy,
            }
            if result["trailing_pe"] is not None and result["forward_pe"] is not None:
                return result
            if partial is None and any(result[k] is not None for k in ["trailing_pe", "forward_pe"]):
                partial = result
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    if partial:
        return partial
    raise RuntimeError(" | ".join(errors) or "No PE data returned")


def safe(name: str, function, errors: list[str], fallback: dict) -> dict:
    try:
        return function()
    except Exception as exc:
        errors.append(f"{name}: {exc}")
        return fallback


def overall_signal(volatility: dict, sentiment: dict, valuation: dict) -> dict:
    details = []
    for key in ["vix", "vxn", "vix3m"]:
        item = volatility[key]
        signal, reason = volatility_signal(item["label"], item["percentile_3y"])
        details.append({"indicator": item["label"], "signal": signal, "reason": reason})

    for key, label in [
        ("equity_put_call", "Equity Put/Call Ratio"),
        ("baa_spread", "Baa信用利差"),
        ("fear_greed", "Fear & Greed Index"),
    ]:
        item = sentiment[key]
        details.append({"indicator": label, "signal": item["signal"], "reason": item["explanation"]})

    for key, market in [("sp500", "标普500"), ("nasdaq100", "纳斯达克100")]:
        signal, reason = forward_pe_signal(valuation[key]["forward_pe"], market)
        details.append({"indicator": f"{market} Forward PE", "signal": signal, "reason": reason})

    buy = sum(item["signal"] == "偏买" for item in details)
    neutral = sum(item["signal"] == "中立" for item in details)
    sell = sum(item["signal"] == "偏卖" for item in details)
    score = buy - sell
    result = "偏买" if score >= 2 else "偏卖" if score <= -2 else "中立"
    return {
        "result": result, "score": score, "buy_count": buy,
        "neutral_count": neutral, "sell_count": sell, "details": details,
        "method_note": "波动、情绪和信用采用反向信号；估值使用Forward PE阈值。",
        "video_note": "指标解释与计算方法，详情请看解释视频。",
        "disclaimer": "仅供参考，不构成任何投资建议。",
    }


def main() -> int:
    errors = []
    volatility = {}
    for key, (symbol, label, market) in VOL.items():
        try:
            series = close_series(symbol)
            volatility[key] = {
                "label": label, "market": market, "source_symbol": symbol,
                "value": round(float(series.iloc[-1]), 4),
                "percentile_1y": percentile(series, 1),
                "percentile_3y": percentile(series, 3),
                "percentile_5y": percentile(series, 5),
                "date": series.index[-1].date().isoformat(), "source": "Yahoo Finance",
            }
        except Exception as exc:
            errors.append(f"{label} ({symbol}): {exc}")
            volatility[key] = {
                "label": label, "market": market, "source_symbol": symbol,
                "value": None, "percentile_1y": None, "percentile_3y": None,
                "percentile_5y": None, "date": "", "source": "Yahoo Finance",
            }

    if volatility["vix"]["value"] is None:
        print("ERROR: VIX data is required.", file=sys.stderr)
        return 1

    sentiment = {
        "equity_put_call": safe("Equity Put/Call", fetch_put_call, errors, {
            "value": None, "date": "", "source": "Cboe", "signal": "中立", "explanation": "抓取失败"
        }),
        "baa_spread": safe("Baa信用利差", fetch_baa, errors, {
            "value": None, "unit": "percentage_points", "date": "", "source": "FRED BAA10Y",
            "signal": "中立", "explanation": "抓取失败"
        }),
        "fear_greed": safe("Fear & Greed Index", fetch_fear_greed, errors, {
            "value": None, "rating": "", "date": "", "source": "CNN Fear & Greed",
            "signal": "中立", "explanation": "抓取失败"
        }),
    }
    valuation = {
        "sp500": safe("标普500 PE", lambda: fetch_pe("^GSPC", "SPY"), errors, {
            "trailing_pe": None, "forward_pe": None, "source_symbol": "^GSPC", "is_etf_proxy": False
        }),
        "nasdaq100": safe("纳斯达克100 PE", lambda: fetch_pe("^NDX", "QQQ"), errors, {
            "trailing_pe": None, "forward_pe": None, "source_symbol": "^NDX", "is_etf_proxy": False
        }),
    }
    payload = {
        "market_date": volatility["vix"]["date"],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "volatility": volatility,
        "sentiment_credit": sentiment,
        "valuation": valuation,
        "overall_signal": overall_signal(volatility, sentiment, valuation),
        "errors": errors,
    }

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "latest_data.json"
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 终端直接显示完整数字，方便从Codex复制给ChatGPT做图和Short。
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nSaved to: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
