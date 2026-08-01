from __future__ import annotations

from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from io import BytesIO
import html
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
PE_HISTORY_URL = (
    "https://raw.githubusercontent.com/pianissix7mo/weekly-etf-report/"
    "main/etf_analyst_target_outputs/ETF_PE_history.xlsx"
)
AAII_FEED_URL = "https://insights.aaii.com/feed"


def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=4,
        read=4,
        connect=4,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update(HEADERS)
    return s


SESSION = make_session()


def get(url: str) -> requests.Response:
    r = SESSION.get(url, timeout=40)
    r.raise_for_status()
    return r


def num(value) -> float | None:
    try:
        value = float(value)
        return round(value, 4) if pd.notna(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def close_series(symbol: str) -> pd.Series:
    df = yf.Ticker(symbol).history(
        period="5y", interval="1d", auto_adjust=False, actions=False
    )
    if df.empty or "Close" not in df:
        raise RuntimeError(f"No price data returned for {symbol}")
    s = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if s.empty:
        raise RuntimeError(f"No valid closes returned for {symbol}")
    idx = pd.to_datetime(s.index)
    try:
        idx = idx.tz_localize(None)
    except TypeError:
        pass
    s.index = idx
    return s.sort_index()


def pct(s: pd.Series, years: int) -> float | None:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    w = s[s.index >= s.index.max() - pd.DateOffset(years=years)]
    return None if w.empty else round(float((w <= float(s.iloc[-1])).mean() * 100), 2)


def ratio_series(a: str, b: str) -> pd.Series:
    df = pd.concat(
        [close_series(a).rename("a"), close_series(b).rename("b")], axis=1
    ).dropna()
    if df.empty:
        raise RuntimeError(f"No overlapping data for {a}/{b}")
    out = (df["a"] / df["b"]).replace([float("inf"), float("-inf")], pd.NA).dropna()
    if out.empty:
        raise RuntimeError(f"No valid ratio data for {a}/{b}")
    return out


def vol_signal(label: str, rank: float | None) -> tuple[str, str]:
    if rank is None:
        return "中立", f"{label}缺少过去3年分位数据"
    if rank >= 75:
        return "偏买", f"{label}位于过去3年高位，恐慌偏高，反向信号偏买"
    if rank <= 25:
        return "偏卖", f"{label}位于过去3年低位，市场平静，反向信号偏卖"
    return "中立", f"{label}位于过去3年中性区间"


def put_call_signal(v: float | None) -> tuple[str, str]:
    if v is None:
        return "中立", "Equity Put/Call缺少数据"
    if v >= 0.90:
        return "偏买", "Put/Call偏高，防御情绪较重，反向信号偏买"
    if v <= 0.55:
        return "偏卖", "Put/Call偏低，情绪偏乐观，反向信号偏卖"
    return "中立", "Put/Call处于中性区间"


def fgi_signal(v: float | None) -> tuple[str, str]:
    if v is None:
        return "中立", "恐惧贪婪指数缺少数据"
    if v <= 25:
        return "偏买", "处于极度恐惧区间，反向信号偏买"
    if v >= 75:
        return "偏卖", "处于极度贪婪区间，反向信号偏卖"
    return "中立", "恐惧贪婪指数处于中性区间"


def aaii_signal(spread: float | None) -> tuple[str, str]:
    if spread is None:
        return "中立", "AAII Bull-Bear Spread缺少数据"
    if spread <= -10:
        return "偏买", "AAII悲观情绪明显高于乐观情绪，反向信号偏买"
    if spread >= 20:
        return "偏卖", "AAII乐观情绪明显高于悲观情绪，反向信号偏卖"
    return "中立", "AAII Bull-Bear Spread未进入极端区间"


def gold_copper_signal(rank: float | None) -> tuple[str, str]:
    if rank is None:
        return "中立", "黄金/铜比缺少过去3年分位数据"
    if rank >= 75:
        return "偏卖", "黄金/铜比位于过去3年高位，避险偏好较强"
    if rank <= 25:
        return "偏买", "黄金/铜比位于过去3年低位，增长与风险偏好较强"
    return "中立", "黄金/铜比位于过去3年中性区间"


def treasury_signal(rank: float | None) -> tuple[str, str]:
    if rank is None:
        return "中立", "10年美债收益率缺少过去3年分位数据"
    if rank >= 75:
        return "偏卖", "10年美债收益率位于过去3年高位，对估值偏不利"
    if rank <= 25:
        return "偏买", "10年美债收益率位于过去3年低位，对估值相对友好"
    return "中立", "10年美债收益率位于过去3年中性区间"


def pe_signal(v: float | None, market: str) -> tuple[str, str]:
    if v is None:
        return "中立", f"{market} Forward PE缺少数据"
    low, high = (17, 22) if market == "标普500" else (22, 30)
    if v <= low:
        return "偏买", f"{market} Forward PE偏低，估值相对便宜"
    if v >= high:
        return "偏卖", f"{market} Forward PE偏高，估值相对偏贵"
    return "中立", f"{market} Forward PE处于中性区间"


def fetch_put_call() -> dict:
    errors = []
    for back in range(11):
        d = date.today() - timedelta(days=back)
        url = f"https://www.cboe.com/us/options/market_statistics/daily/?dt={d.isoformat()}"
        try:
            text = html.unescape(re.sub(r"<[^>]+>", " ", get(url).text))
            text = re.sub(r"\s+", " ", text)
            m = re.search(r"EQUITY PUT/CALL RATIO\s+([0-9]+(?:\.[0-9]+)?)", text, re.I)
            if m:
                value = round(float(m.group(1)), 4)
                signal, explanation = put_call_signal(value)
                return {"value": value, "date": d.isoformat(), "source": "Cboe", "signal": signal, "explanation": explanation}
            errors.append(f"{d}: ratio not found")
        except Exception as exc:
            errors.append(f"{d}: {exc}")
    raise RuntimeError(" | ".join(errors[-3:]))


def fetch_fear_greed() -> dict:
    item = get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata").json()["fear_and_greed"]
    ts = item.get("timestamp")
    if isinstance(ts, (int, float)):
        as_of = datetime.fromtimestamp(float(ts) / 1000).date().isoformat()
    elif isinstance(ts, str) and ts:
        try:
            as_of = datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            as_of = date.today().isoformat()
    else:
        as_of = date.today().isoformat()
    value = round(float(item["score"]), 2)
    signal, explanation = fgi_signal(value)
    return {"value": value, "rating": str(item.get("rating", "")), "date": as_of, "source": "CNN Fear & Greed", "signal": signal, "explanation": explanation}


def plain_text(raw: str) -> str:
    raw = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def parse_aaii(text: str) -> tuple[float, float, float]:
    m = re.search(r"This week.?s Sentiment Survey results\s*:?(.*?)(?:Historical averages|$)", text, re.I | re.S)
    section = m.group(1) if m else text
    values = []
    for label in ["Bullish", "Neutral", "Bearish"]:
        found = re.search(rf"{label}\s*:\s*([0-9]+(?:\.[0-9]+)?)%", section, re.I)
        if not found:
            raise RuntimeError(f"AAII {label} value not found")
        values.append(round(float(found.group(1)), 2))
    return tuple(values)


def fetch_aaii() -> dict:
    root = ET.fromstring(get(AAII_FEED_URL).content)
    tag = "{http://purl.org/rss/1.0/modules/content/}encoded"
    posts = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if "aaii sentiment survey" not in title.lower():
            continue
        posts.append(((item.findtext("link") or "").strip(), (item.findtext("pubDate") or "").strip(), item.findtext(tag) or item.findtext("description") or ""))
    if not posts:
        raise RuntimeError("No AAII Sentiment Survey post found in official feed")

    last_error = None
    for link, published, body in posts[:8]:
        try:
            text = plain_text(body)
            try:
                bullish, neutral, bearish = parse_aaii(text)
            except Exception:
                bullish, neutral, bearish = parse_aaii(plain_text(get(link).text))
            spread = round(bullish - bearish, 2)
            signal, explanation = aaii_signal(spread)
            try:
                as_of = parsedate_to_datetime(published).date().isoformat()
            except Exception:
                as_of = ""
            return {"bullish": bullish, "neutral": neutral, "bearish": bearish, "bull_bear_spread": spread, "date": as_of, "frequency": "weekly", "source": "AAII Sentiment Survey", "source_url": link, "signal": signal, "explanation": explanation}
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not parse recent AAII survey posts: {last_error}")


def fetch_gold_copper() -> dict:
    s = ratio_series("GC=F", "HG=F")
    p1, p3, p5 = pct(s, 1), pct(s, 3), pct(s, 5)
    signal, explanation = gold_copper_signal(p3)
    return {"value": round(float(s.iloc[-1]), 4), "date": s.index[-1].date().isoformat(), "source": "Yahoo Finance GC=F / HG=F", "percentile_1y": p1, "percentile_3y": p3, "percentile_5y": p5, "signal": signal, "explanation": explanation, "note": "绝对值受期货报价单位影响，综合判断只使用历史百分位。"}


def fetch_treasury() -> dict:
    raw = close_series("^TNX")
    s = raw / 10 if float(raw.tail(60).median()) > 20 else raw
    p1, p3, p5 = pct(s, 1), pct(s, 3), pct(s, 5)
    signal, explanation = treasury_signal(p3)
    return {"value": round(float(s.iloc[-1]), 4), "unit": "percent", "date": s.index[-1].date().isoformat(), "source": "Yahoo Finance ^TNX", "percentile_1y": p1, "percentile_3y": p3, "percentile_5y": p5, "signal": signal, "explanation": explanation}


def fetch_pe_history() -> dict:
    df = pd.read_excel(BytesIO(get(PE_HISTORY_URL).content), engine="openpyxl")
    required = {"Date", "ETF", "PE Ratio", "Forward PE"}
    missing = required.difference(df.columns)
    if missing:
        raise RuntimeError(f"PE history missing columns: {sorted(missing)}")
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["ETF"] = df["ETF"].astype(str).str.upper().str.strip()
    for col in ["PE Ratio", "Forward PE", "PE coverage", "Forward PE coverage"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    out = {}
    for etf, key, market in [("SPY", "sp500", "标普500"), ("QQQ", "nasdaq100", "纳斯达克100")]:
        rows = df[df["ETF"] == etf].dropna(subset=["Date"]).sort_values("Date")
        complete = rows.dropna(subset=["PE Ratio", "Forward PE"])
        if complete.empty:
            raise RuntimeError(f"No complete PE and Forward PE row for {etf}")
        row = complete.iloc[-1]
        out[key] = {"market": market, "trailing_pe": num(row["PE Ratio"]), "forward_pe": num(row["Forward PE"]), "source_symbol": etf, "is_etf_proxy": True, "pe_coverage": num(row.get("PE coverage")), "forward_pe_coverage": num(row.get("Forward PE coverage")), "source": "weekly-etf-report / ETF_PE_history.xlsx", "date": pd.Timestamp(row["Date"]).date().isoformat()}
    return out


def safe(name: str, fn, errors: list[str], fallback: dict) -> dict:
    try:
        return fn()
    except Exception as exc:
        errors.append(f"{name}: {exc}")
        return fallback


def overall(vol: dict, macro: dict, valuation: dict) -> dict:
    details = []
    for key in ["vix", "vxn"]:
        item = vol[key]
        signal, reason = vol_signal(item["label"], item["percentile_3y"])
        details.append({"indicator": item["label"], "signal": signal, "reason": reason, "included": item["value"] is not None})

    for key, label in [("equity_put_call", "Equity Put/Call Ratio"), ("fear_greed", "Fear & Greed Index"), ("aaii_sentiment", "AAII Bull-Bear Spread"), ("gold_copper_ratio", "Gold / Copper Ratio"), ("treasury_10y", "10Y Treasury Yield")]:
        item = macro[key]
        available = item.get("bull_bear_spread") is not None if key == "aaii_sentiment" else item.get("value") is not None
        details.append({"indicator": label, "signal": item["signal"], "reason": item["explanation"], "included": available})

    for key, market in [("sp500", "标普500"), ("nasdaq100", "纳斯达克100")]:
        signal, reason = pe_signal(valuation[key]["forward_pe"], market)
        details.append({"indicator": f"{market} Forward PE", "signal": signal, "reason": reason, "included": valuation[key]["forward_pe"] is not None})

    valid = [x for x in details if x["included"]]
    buy = sum(x["signal"] == "偏买" for x in valid)
    neutral = sum(x["signal"] == "中立" for x in valid)
    sell = sum(x["signal"] == "偏卖" for x in valid)
    score = buy - sell
    return {"result": "偏买" if score >= 2 else "偏卖" if score <= -2 else "中立", "score": score, "buy_count": buy, "neutral_count": neutral, "sell_count": sell, "available_count": len(valid), "missing_count": len(details) - len(valid), "details": details, "method_note": "VIX、VXN、Put/Call、Fear & Greed及AAII采用反向情绪信号；Gold/Copper与10Y Treasury采用方向信号；估值读取ETF PE历史表。", "disclaimer": "仅供参考，不构成任何投资建议。"}


def main() -> int:
    errors: list[str] = []
    vol = {}
    for key, (symbol, label, market) in VOL.items():
        try:
            s = close_series(symbol)
            vol[key] = {"label": label, "market": market, "source_symbol": symbol, "value": round(float(s.iloc[-1]), 4), "percentile_1y": pct(s, 1), "percentile_3y": pct(s, 3), "percentile_5y": pct(s, 5), "date": s.index[-1].date().isoformat(), "source": "Yahoo Finance"}
        except Exception as exc:
            errors.append(f"{label} ({symbol}): {exc}")
            vol[key] = {"label": label, "market": market, "source_symbol": symbol, "value": None, "percentile_1y": None, "percentile_3y": None, "percentile_5y": None, "date": "", "source": "Yahoo Finance"}

    if vol["vix"]["value"] is None:
        print("ERROR: VIX data is required.", file=sys.stderr)
        return 1

    macro = {
        "equity_put_call": safe("Equity Put/Call", fetch_put_call, errors, {"value": None, "date": "", "source": "Cboe", "signal": "中立", "explanation": "抓取失败"}),
        "fear_greed": safe("Fear & Greed", fetch_fear_greed, errors, {"value": None, "rating": "", "date": "", "source": "CNN", "signal": "中立", "explanation": "抓取失败"}),
        "aaii_sentiment": safe("AAII Sentiment", fetch_aaii, errors, {"bullish": None, "neutral": None, "bearish": None, "bull_bear_spread": None, "date": "", "frequency": "weekly", "source": "AAII", "source_url": "", "signal": "中立", "explanation": "抓取失败"}),
        "gold_copper_ratio": safe("Gold/Copper", fetch_gold_copper, errors, {"value": None, "date": "", "source": "Yahoo Finance GC=F / HG=F", "percentile_1y": None, "percentile_3y": None, "percentile_5y": None, "signal": "中立", "explanation": "抓取失败"}),
        "treasury_10y": safe("10Y Treasury", fetch_treasury, errors, {"value": None, "unit": "percent", "date": "", "source": "Yahoo Finance ^TNX", "percentile_1y": None, "percentile_3y": None, "percentile_5y": None, "signal": "中立", "explanation": "抓取失败"}),
    }

    valuation = safe("ETF PE history", fetch_pe_history, errors, {
        "sp500": {"market": "标普500", "trailing_pe": None, "forward_pe": None, "source_symbol": "SPY", "is_etf_proxy": True, "source": "weekly-etf-report / ETF_PE_history.xlsx", "date": ""},
        "nasdaq100": {"market": "纳斯达克100", "trailing_pe": None, "forward_pe": None, "source_symbol": "QQQ", "is_etf_proxy": True, "source": "weekly-etf-report / ETF_PE_history.xlsx", "date": ""},
    })

    payload = {"market_date": vol["vix"]["date"], "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "volatility": vol, "macro": macro, "valuation": valuation, "overall_signal": overall(vol, macro, valuation), "errors": errors}
    out = Path(__file__).resolve().parent / "output"
    out.mkdir(exist_ok=True)
    path = out / "latest_data.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nSaved to: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
