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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yfinance as yf


VOL = {
    "vix": ("^VIX", "VIX", "标普500"),
    "vxn": ("^VXN", "VXN", "纳斯达克100"),
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


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)
    return session


SESSION = build_session()


def get(url: str) -> requests.Response:
    response = SESSION.get(url, timeout=30)
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


def ratio_series(numerator_symbol: str, denominator_symbol: str) -> pd.Series:
    num = close_series(numerator_symbol)
    den = close_series(denominator_symbol)
    frame = pd.concat([num.rename("num"), den.rename("den")], axis=1).dropna()
    if frame.empty:
        raise RuntimeError(
            f"No overlapping data for ratio {numerator_symbol}/{denominator_symbol}"
        )
    ratio = frame["num"] / frame["den"]
    ratio = ratio.replace([float("inf"), float("-inf")], pd.NA).dropna()
    if ratio.empty:
        raise RuntimeError(
            f"No valid ratio values for {numerator_symbol}/{denominator_symbol}"
        )
    return ratio


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


def fear_greed_signal(value: float | None) -> tuple[str, str]:
    if value is None:
        return "中立", "恐惧贪婪指数缺少数据"
    if value <= 25:
        return "偏买", "处于极度恐惧区间，反向信号偏买"
    if value >= 75:
        return "偏卖", "处于极度贪婪区间，反向信号偏卖"
    return "中立", "恐惧贪婪指数处于中性区间"


def gold_copper_signal(rank: float | None) -> tuple[str, str]:
    if rank is None:
        return "中立", "黄金/铜比缺少过去3年分位数据"
    if rank >= 75:
        return "偏卖", "黄金/铜比位于过去3年高位，避险偏好较强，风险信号偏卖"
    if rank <= 25:
        return "偏买", "黄金/铜比位于过去3年低位，风险偏好较强，风险信号偏买"
    return "中立", "黄金/铜比位于过去3年中性区间"


def treasury_signal(rank: float | None) -> tuple[str, str]:
    if rank is None:
        return "中立", "10年美债收益率缺少过去3年分位数据"
    if rank >= 75:
        return "偏卖", "10年美债收益率位于过去3年高位，对估值偏不利"
    if rank <= 25:
        return "偏买", "10年美债收益率位于过去3年低位，对估值相对友好"
    return "中立", "10年美债收益率位于过去3年中性区间"


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


def fetch_fear_greed() -> dict:
    item = get(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    ).json()["fear_and_greed"]

    timestamp = item.get("timestamp")
    if isinstance(timestamp, (int, float)):
        data_date = datetime.fromtimestamp(float(timestamp) / 1000).date().isoformat()
    elif isinstance(timestamp, str) and timestamp:
        try:
            data_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            data_date = date.today().isoformat()
    else:
        data_date = date.today().isoformat()

    value = round(float(item["score"]), 2)
    signal, explanation = fear_greed_signal(value)
    return {
        "value": value,
        "rating": str(item.get("rating", "")),
        "date": data_date,
        "source": "CNN Fear & Greed",
        "signal": signal,
        "explanation": explanation,
    }


def fetch_gold_copper_ratio() -> dict:
    series = ratio_series("GC=F", "HG=F")
    value = round(float(series.iloc[-1]), 4)
    rank_1y = percentile(series, 1)
    rank_3y = percentile(series, 3)
    rank_5y = percentile(series, 5)
    signal, explanation = gold_copper_signal(rank_3y)
    return {
        "value": value,
        "date": series.index[-1].date().isoformat(),
        "source": "Yahoo Finance GC=F / HG=F",
        "percentile_1y": rank_1y,
        "percentile_3y": rank_3y,
        "percentile_5y": rank_5y,
        "signal": signal,
        "explanation": explanation,
    }


def fetch_treasury_10y() -> dict:
    series_raw = close_series("^TNX")
    # Yahoo的 ^TNX 通常是收益率 * 10，例如 42.5 表示 4.25%
    series = series_raw / 10.0
    value = round(float(series.iloc[-1]), 4)
    rank_1y = percentile(series, 1)
    rank_3y = percentile(series, 3)
    rank_5y = percentile(series, 5)
    signal, explanation = treasury_signal(rank_3y)
    return {
        "value": value,
        "unit": "percent",
        "date": series.index[-1].date().isoformat(),
        "source": "Yahoo Finance ^TNX",
        "percentile_1y": rank_1y,
        "percentile_3y": rank_3y,
        "percentile_5y": rank_5y,
        "signal": signal,
        "explanation": explanation,
    }


def fetch_ssga_index_pe(page_key: str) -> dict:
    config = SSGA_INDEX_PAGES[page_key]
    html_text = get(config["url"]).text

    date_match = re.search(
        r"As of\s*</span>\s*<span[^>]*>([^<]+)</span>", html_text, re.I
    )

    trailing_match = re.search(
        r"Price/Earnings\s*</span>\s*<span[^>]*>\s*([0-9]+(?:\.[0-9]+)?)",
        html_text,
        re.I,
    )

    forward_match = re.search(
        r"Price/Earnings Ratio FY1\s*</span>\s*<span[^>]*>\s*([0-9]+(?:\.[0-9]+)?)",
        html_text,
        re.I,
    )

    if not trailing_match and not forward_match:
        raise RuntimeError(f"Could not parse State Street valuation data for {page_key}")

    raw_date = date_match.group(1).strip() if date_match else ""
    parsed_date = raw_date
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            parsed_date = datetime.strptime(raw_date, fmt).date().isoformat()
            break
        except Exception:
            pass

    return {
        "trailing_pe": positive_number(trailing_match.group(1)) if trailing_match else None,
        "forward_pe": positive_number(forward_match.group(1)) if forward_match else None,
        "source_symbol": config["symbol"],
        "is_etf_proxy": False,
        "source": "State Street Index Characteristics",
        "date": parsed_date,
    }


def fetch_pe(index_symbol: str, etf_symbol: str, page_key: str) -> dict:
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

            if partial is None and any(
                result[key] is not None for key in ["trailing_pe", "forward_pe"]
            ):
                partial = result

        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    try:
        ssga = fetch_ssga_index_pe(page_key)
        if ssga["trailing_pe"] is not None or ssga["forward_pe"] is not None:
            if partial:
                partial["trailing_pe"] = partial["trailing_pe"] or ssga["trailing_pe"]
                partial["forward_pe"] = partial["forward_pe"] or ssga["forward_pe"]
                partial["source_symbol"] = partial["source_symbol"] or ssga["source_symbol"]
                partial["source"] = partial["source"] if partial["forward_pe"] else ssga["source"]
                partial["date"] = partial["date"] or ssga["date"]
                return partial
            return ssga
    except Exception as exc:
        errors.append(f"State Street {page_key}: {exc}")

    if partial:
        return partial

    raise RuntimeError(" | ".join(errors) or "No PE data returned")


def safe(name: str, function, errors: list[str], fallback: dict) -> dict:
    try:
        return function()
    except Exception as exc:
        errors.append(f"{name}: {exc}")
        return fallback


def overall_signal(volatility: dict, macro: dict, valuation: dict) -> dict:
    details = []

    for key in ["vix", "vxn"]:
        item = volatility[key]
        signal, reason = volatility_signal(item["label"], item["percentile_3y"])
        details.append({
            "indicator": item["label"],
            "signal": signal,
            "reason": reason,
            "included": item["value"] is not None,
        })

    for key, label in [
        ("equity_put_call", "Equity Put/Call Ratio"),
        ("fear_greed", "Fear & Greed Index"),
        ("gold_copper_ratio", "Gold / Copper Ratio"),
        ("treasury_10y", "10Y Treasury Yield"),
    ]:
        item = macro[key]
        details.append({
            "indicator": label,
            "signal": item["signal"],
            "reason": item["explanation"],
            "included": item["value"] is not None,
        })

    for key, market in [("sp500", "标普500"), ("nasdaq100", "纳斯达克100")]:
        signal, reason = forward_pe_signal(valuation[key]["forward_pe"], market)
        details.append({
            "indicator": f"{market} Forward PE",
            "signal": signal,
            "reason": reason,
            "included": valuation[key]["forward_pe"] is not None,
        })

    valid_details = [item for item in details if item["included"]]
    buy = sum(item["signal"] == "偏买" for item in valid_details)
    neutral = sum(item["signal"] == "中立" for item in valid_details)
    sell = sum(item["signal"] == "偏卖" for item in valid_details)
    score = buy - sell

    result = "偏买" if score >= 2 else "偏卖" if score <= -2 else "中立"

    return {
        "result": result,
        "score": score,
        "buy_count": buy,
        "neutral_count": neutral,
        "sell_count": sell,
        "available_count": len(valid_details),
        "missing_count": len(details) - len(valid_details),
        "details": details,
        "method_note": (
            "VIX、VXN、Put/Call、Fear & Greed采用反向信号；"
            "Gold/Copper与10Y Treasury采用方向信号；"
            "估值使用Forward PE阈值。"
        ),
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

    macro = {
        "equity_put_call": safe(
            "Equity Put/Call",
            fetch_put_call,
            errors,
            {
                "value": None,
                "date": "",
                "source": "Cboe",
                "signal": "中立",
                "explanation": "抓取失败",
            },
        ),
        "fear_greed": safe(
            "Fear & Greed Index",
            fetch_fear_greed,
            errors,
            {
                "value": None,
                "rating": "",
                "date": "",
                "source": "CNN Fear & Greed",
                "signal": "中立",
                "explanation": "抓取失败",
            },
        ),
        "gold_copper_ratio": safe(
            "Gold/Copper Ratio",
            fetch_gold_copper_ratio,
            errors,
            {
                "value": None,
                "date": "",
                "source": "Yahoo Finance GC=F / HG=F",
                "percentile_1y": None,
                "percentile_3y": None,
                "percentile_5y": None,
                "signal": "中立",
                "explanation": "抓取失败",
            },
        ),
        "treasury_10y": safe(
            "10Y Treasury Yield",
            fetch_treasury_10y,
            errors,
            {
                "value": None,
                "unit": "percent",
                "date": "",
                "source": "Yahoo Finance ^TNX",
                "percentile_1y": None,
                "percentile_3y": None,
                "percentile_5y": None,
                "signal": "中立",
                "explanation": "抓取失败",
            },
        ),
    }

    valuation = {
        "sp500": safe(
            "标普500 PE",
            lambda: fetch_pe("^GSPC", "SPY", "sp500"),
            errors,
            {
                "trailing_pe": None,
                "forward_pe": None,
                "source_symbol": "^GSPC",
                "is_etf_proxy": False,
                "source": "",
                "date": "",
            },
        ),
        "nasdaq100": safe(
            "纳斯达克100 PE",
            lambda: fetch_pe("^NDX", "QQQ", "nasdaq100"),
            errors,
            {
                "trailing_pe": None,
                "forward_pe": None,
                "source_symbol": "^NDX",
                "is_etf_proxy": False,
                "source": "",
                "date": "",
            },
        ),
    }

    payload = {
        "market_date": volatility["vix"]["date"],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "volatility": volatility,
        "macro": macro,
        "valuation": valuation,
        "overall_signal": {},
        "errors": errors,
    }

    payload["overall_signal"] = overall_signal(volatility, macro, valuation)

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "latest_data.json"
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nSaved to: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
