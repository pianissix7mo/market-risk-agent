from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import StringIO
import html
import json
from pathlib import Path
import re
import sys
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yfinance as yf


VOL = {
    "vix": ("^VIX", "VIX", "标普500"),
    "vxn": ("^VXN", "VXN", "纳斯达克100"),
    "vix3m": ("^VIX3M", "VIX3M", "标普500"),
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SSGA_INDEX_PAGES = {
    "sp500": {
        "url": "https://www.ssga.com/us/en/individual/etfs/state-street-spdr-portfolio-sp-500-etf-spym",
        "market": "标普500",
        "symbol": "S&P 500 Index via SPYM",
    },
    "nasdaq100": {
        "url": "https://www.ssga.com/us/en/individual/etfs/state-street-spdr-portfolio-nasdaq-100-etf-qndx",
        "market": "纳斯达克100",
        "symbol": "Nasdaq-100 Index via QNDX",
    },
}


def make_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update(HEADERS)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = make_session()


def get(url: str, timeout: int = 35) -> requests.Response:
    response = SESSION.get(url, timeout=timeout)
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


def parse_timestamp(value) -> str:
    if value in (None, ""):
        return date.today().isoformat()

    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc).date().isoformat()

    text = str(value).strip()
    try:
        number = float(text)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc).date().isoformat()
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        parsed = pd.to_datetime(text, errors="coerce", utc=True)
        if pd.isna(parsed):
            raise ValueError(f"Unsupported timestamp format: {value!r}")
        return parsed.date().isoformat()


def volatility_signal(item: dict) -> tuple[str, str, bool]:
    label = item["label"]
    if item.get("is_stale"):
        return "中立", f"{label}数据滞后{item['stale_days']}天，本次不计入综合判断", False
    rank = item.get("percentile_3y")
    if rank is None:
        return "中立", f"{label}缺少过去3年分位数据", False
    if rank >= 75:
        return "偏买", f"{label}位于过去3年高位，恐慌偏高，反向信号偏买", True
    if rank <= 25:
        return "偏卖", f"{label}位于过去3年低位，市场平静，反向信号偏卖", True
    return "中立", f"{label}位于过去3年中性区间", True


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
                    "value": value,
                    "date": data_date.isoformat(),
                    "source": "Cboe",
                    "signal": signal,
                    "explanation": explanation,
                }
            errors.append(f"{data_date}: ratio not found")
        except Exception as exc:
            errors.append(f"{data_date}: {exc}")
    raise RuntimeError(" | ".join(errors[-3:]))


def parse_fred_csv(csv_text: str, series_id: str) -> dict:
    frame = pd.read_csv(StringIO(csv_text))
    if series_id not in frame:
        raise RuntimeError(f"{series_id} column missing")
    frame[series_id] = pd.to_numeric(frame[series_id], errors="coerce")
    frame = frame.dropna(subset=[series_id])
    if frame.empty:
        raise RuntimeError(f"No {series_id} observations returned")
    row = frame.iloc[-1]
    date_column = "observation_date" if "observation_date" in frame else frame.columns[0]
    return {"value": round(float(row[series_id]), 4), "date": str(row[date_column])}


def fetch_baa() -> dict:
    urls = [
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAA10Y",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?fq=Daily&fam=avg&fgst=lin&id=BAA10Y",
    ]
    failures = []
    for url in urls:
        try:
            result = parse_fred_csv(get(url).text, "BAA10Y")
            signal, explanation = baa_signal(result["value"])
            return {
                **result,
                "unit": "percentage_points",
                "source": "FRED BAA10Y",
                "signal": signal,
                "explanation": explanation,
            }
        except Exception as exc:
            failures.append(str(exc))
            time.sleep(1)

    try:
        baa = parse_fred_csv(get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DBAA").text, "DBAA")
        treasury = parse_fred_csv(get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10").text, "DGS10")
        value = round(baa["value"] - treasury["value"], 4)
        signal, explanation = baa_signal(value)
        return {
            "value": value,
            "unit": "percentage_points",
            "date": min(baa["date"], treasury["date"]),
            "source": "FRED DBAA - DGS10",
            "signal": signal,
            "explanation": explanation,
        }
    except Exception as exc:
        failures.append(str(exc))

    raise RuntimeError(" | ".join(failures[-3:]))


def fetch_fear_greed() -> dict:
    item = get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata").json()["fear_and_greed"]
    value = round(float(item["score"]), 2)
    signal, explanation = fear_greed_signal(value)
    return {
        "value": value,
        "rating": str(item.get("rating", "")),
        "date": parse_timestamp(item.get("timestamp")),
        "source": "CNN Fear & Greed",
        "signal": signal,
        "explanation": explanation,
    }


def fetch_yahoo_pe(index_symbol: str, etf_symbol: str) -> dict:
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
                "source": "Yahoo Finance",
                "date": "",
            }
            if result["trailing_pe"] is not None and result["forward_pe"] is not None:
                return result
            if partial is None and any(result[k] is not None for k in ["trailing_pe", "forward_pe"]):
                partial = result
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    if partial:
        return partial
    raise RuntimeError(" | ".join(errors) or "No Yahoo PE data returned")


def extract_number_after(text: str, label_pattern: str) -> float | None:
    match = re.search(label_pattern + r".{0,900}?([0-9]{1,3}(?:\.[0-9]+)?)", text, re.I)
    return positive_number(match.group(1)) if match else None


def fetch_ssga_index_pe(key: str) -> dict:
    config = SSGA_INDEX_PAGES[key]
    raw = get(config["url"]).text
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"\s+", " ", text)

    start = text.lower().find("index characteristics")
    section = text[start:start + 7000] if start >= 0 else text

    forward_pe = extract_number_after(section, r"Price/Earnings Ratio FY1")
    trailing_pe = extract_number_after(section, r"Price/Earnings(?! Ratio FY1)")
    if trailing_pe is None and forward_pe is None:
        raise RuntimeError("State Street index PE fields not found")

    date_match = re.search(
        r"Index Characteristics as of\s+([A-Za-z]{3}\s+\d{1,2}\s+\d{4})",
        section,
        re.I,
    )
    data_date = ""
    if date_match:
        parsed = pd.to_datetime(date_match.group(1), errors="coerce")
        if not pd.isna(parsed):
            data_date = parsed.date().isoformat()

    return {
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "source_symbol": config["symbol"],
        "is_etf_proxy": False,
        "source": "State Street Index Characteristics",
        "date": data_date,
    }


def fetch_pe(key: str, index_symbol: str, etf_symbol: str) -> dict:
    yahoo_error = None
    try:
        yahoo = fetch_yahoo_pe(index_symbol, etf_symbol)
    except Exception as exc:
        yahoo = {
            "trailing_pe": None,
            "forward_pe": None,
            "source_symbol": index_symbol,
            "is_etf_proxy": False,
            "source": "Yahoo Finance",
            "date": "",
        }
        yahoo_error = str(exc)

    if yahoo["trailing_pe"] is not None and yahoo["forward_pe"] is not None:
        return yahoo

    try:
        official = fetch_ssga_index_pe(key)
        if official["trailing_pe"] is None:
            official["trailing_pe"] = yahoo["trailing_pe"]
        if official["forward_pe"] is None:
            official["forward_pe"] = yahoo["forward_pe"]
        return official
    except Exception as official_error:
        if yahoo["trailing_pe"] is not None or yahoo["forward_pe"] is not None:
            yahoo["fallback_error"] = str(official_error)
            return yahoo
        raise RuntimeError(f"Yahoo: {yahoo_error}; State Street: {official_error}")


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
        signal, reason, included = volatility_signal(item)
        details.append({
            "indicator": item["label"],
            "signal": signal,
            "reason": reason,
            "included": included,
        })

    for key, label in [
        ("equity_put_call", "Equity Put/Call Ratio"),
        ("baa_spread", "Baa信用利差"),
        ("fear_greed", "Fear & Greed Index"),
    ]:
        item = sentiment[key]
        included = item.get("value") is not None
        details.append({
            "indicator": label,
            "signal": item["signal"],
            "reason": item["explanation"],
            "included": included,
        })

    for key, market in [("sp500", "标普500"), ("nasdaq100", "纳斯达克100")]:
        signal, reason = forward_pe_signal(valuation[key]["forward_pe"], market)
        included = valuation[key]["forward_pe"] is not None
        details.append({
            "indicator": f"{market} Forward PE",
            "signal": signal,
            "reason": reason,
            "included": included,
        })

    included_details = [item for item in details if item["included"]]
    buy = sum(item["signal"] == "偏买" for item in included_details)
    neutral = sum(item["signal"] == "中立" for item in included_details)
    sell = sum(item["signal"] == "偏卖" for item in included_details)
    score = buy - sell
    result = "偏买" if score >= 2 else "偏卖" if score <= -2 else "中立"

    return {
        "result": result,
        "score": score,
        "buy_count": buy,
        "neutral_count": neutral,
        "sell_count": sell,
        "available_count": len(included_details),
        "missing_or_stale_count": len(details) - len(included_details),
        "details": details,
        "method_note": "波动、情绪和信用采用反向信号；估值使用Forward PE阈值；缺失或过期数据不计分。",
        "video_note": "指标解释与计算方法，详情请看解释视频。",
        "disclaimer": "仅供参考，不构成任何投资建议。",
    }


def main() -> int:
    errors: list[str] = []
    volatility = {}

    for key, (symbol, label, market) in VOL.items():
        try:
            series = close_series(symbol)
            volatility[key] = {
                "label": label,
                "market": market,
                "source_symbol": symbol,
                "value": round(float(series.iloc[-1]), 4),
                "percentile_1y": percentile(series, 1),
                "percentile_3y": percentile(series, 3),
                "percentile_5y": percentile(series, 5),
                "date": series.index[-1].date().isoformat(),
                "source": "Yahoo Finance",
            }
        except Exception as exc:
            errors.append(f"{label} ({symbol}): {exc}")
            volatility[key] = {
                "label": label,
                "market": market,
                "source_symbol": symbol,
                "value": None,
                "percentile_1y": None,
                "percentile_3y": None,
                "percentile_5y": None,
                "date": "",
                "source": "Yahoo Finance",
            }

    if volatility["vix"]["value"] is None:
        print("ERROR: VIX data is required.", file=sys.stderr)
        return 1

    market_date = date.fromisoformat(volatility["vix"]["date"])
    for item in volatility.values():
        if item["date"]:
            lag = max(0, (market_date - date.fromisoformat(item["date"])).days)
            item["stale_days"] = lag
            item["is_stale"] = lag > 5
        else:
            item["stale_days"] = None
            item["is_stale"] = True

    sentiment = {
        "equity_put_call": safe("Equity Put/Call", fetch_put_call, errors, {
            "value": None,
            "date": "",
            "source": "Cboe",
            "signal": "中立",
            "explanation": "抓取失败",
        }),
        "baa_spread": safe("Baa信用利差", fetch_baa, errors, {
            "value": None,
            "unit": "percentage_points",
            "date": "",
            "source": "FRED BAA10Y",
            "signal": "中立",
            "explanation": "抓取失败",
        }),
        "fear_greed": safe("Fear & Greed Index", fetch_fear_greed, errors, {
            "value": None,
            "rating": "",
            "date": "",
            "source": "CNN Fear & Greed",
            "signal": "中立",
            "explanation": "抓取失败",
        }),
    }

    valuation = {
        "sp500": safe("标普500 PE", lambda: fetch_pe("sp500", "^GSPC", "SPY"), errors, {
            "trailing_pe": None,
            "forward_pe": None,
            "source_symbol": "^GSPC",
            "is_etf_proxy": False,
            "source": "",
            "date": "",
        }),
        "nasdaq100": safe("纳斯达克100 PE", lambda: fetch_pe("nasdaq100", "^NDX", "QQQ"), errors, {
            "trailing_pe": None,
            "forward_pe": None,
            "source_symbol": "^NDX",
            "is_etf_proxy": False,
            "source": "",
            "date": "",
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

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nSaved to: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
