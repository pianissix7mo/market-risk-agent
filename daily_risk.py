from __future__ import annotations

from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from io import BytesIO
import html, json, re, sys, time
from pathlib import Path
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yfinance as yf

VOL = {"vix": ("^VIX", "VIX", "标普500"), "vxn": ("^VXN", "VXN", "纳斯达克100")}
HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
PE_URL = "https://raw.githubusercontent.com/pianissix7mo/weekly-etf-report/main/etf_analyst_target_outputs/ETF_PE_history.xlsx"
AAII_URL = "https://www.aaii.com/sentimentsurvey"

MIN_QQQ_PE_COVERAGE = 0.50
MIN_AVAILABLE_INDICATORS = 6
QQQ_PE_ATTEMPTS = 3
QQQ_PE_RETRY_SECONDS = 15


def make_session():
    s = requests.Session()
    retry = Retry(total=4, read=4, connect=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter); s.mount("https://", adapter); s.headers.update(HEADERS)
    return s


SESSION = make_session()


def get(url):
    r = SESSION.get(url, timeout=40); r.raise_for_status(); return r


def num(value):
    try:
        value = float(value)
        return round(value, 4) if pd.notna(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def close_series(symbol):
    df = yf.Ticker(symbol).history(period="5y", interval="1d", auto_adjust=False, actions=False)
    if df.empty or "Close" not in df: raise RuntimeError(f"No price data returned for {symbol}")
    s = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if s.empty: raise RuntimeError(f"No valid closes returned for {symbol}")
    idx = pd.to_datetime(s.index)
    try: idx = idx.tz_localize(None)
    except TypeError: pass
    s.index = idx
    return s.sort_index()


def pct(s, years):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty: return None
    w = s[s.index >= s.index.max() - pd.DateOffset(years=years)]
    return None if w.empty else round(float((w <= float(s.iloc[-1])).mean() * 100), 2)


def ratio_series(a, b):
    df = pd.concat([close_series(a).rename("a"), close_series(b).rename("b")], axis=1).dropna()
    if df.empty: raise RuntimeError(f"No overlapping data for {a}/{b}")
    s = (df["a"] / df["b"]).replace([float("inf"), float("-inf")], pd.NA).dropna()
    if s.empty: raise RuntimeError(f"No valid ratio data for {a}/{b}")
    return s


def vol_signal(label, rank):
    if rank is None: return "中立", f"{label}缺少过去3年分位数据"
    if rank >= 75: return "偏买", f"{label}位于过去3年高位，恐慌偏高，反向信号偏买"
    if rank <= 25: return "偏卖", f"{label}位于过去3年低位，市场平静，反向信号偏卖"
    return "中立", f"{label}位于过去3年中性区间"


def put_call_signal(v):
    if v is None: return "中立", "Equity Put/Call缺少数据"
    if v >= 0.90: return "偏买", "Put/Call偏高，防御情绪较重，反向信号偏买"
    if v <= 0.55: return "偏卖", "Put/Call偏低，情绪偏乐观，反向信号偏卖"
    return "中立", "Put/Call处于中性区间"


def fgi_signal(v):
    if v is None: return "中立", "恐惧贪婪指数缺少数据"
    if v <= 25: return "偏买", "处于极度恐惧区间，反向信号偏买"
    if v >= 75: return "偏卖", "处于极度贪婪区间，反向信号偏卖"
    return "中立", "恐惧贪婪指数处于中性区间"


def aaii_signal(spread):
    if spread is None: return "中立", "AAII Bull-Bear Spread缺少数据"
    if spread <= -10: return "偏买", "AAII悲观情绪明显高于乐观情绪，反向信号偏买"
    if spread >= 20: return "偏卖", "AAII乐观情绪明显高于悲观情绪，反向信号偏卖"
    return "中立", "AAII Bull-Bear Spread未进入极端区间"


def gold_copper_signal(rank):
    if rank is None: return "中立", "黄金/铜比缺少过去3年分位数据"
    if rank >= 75: return "偏买", "黄金/铜比位于过去3年高位，避险情绪较强，反向信号偏买"
    if rank <= 25: return "偏卖", "黄金/铜比位于过去3年低位，风险偏好较强，反向信号偏卖"
    return "中立", "黄金/铜比位于过去3年中性区间"


def treasury_signal(rank):
    if rank is None: return "中立", "10年美债收益率缺少过去3年分位数据"
    if rank >= 75: return "偏卖", "10年美债收益率位于过去3年高位，对估值偏不利"
    if rank <= 25: return "偏买", "10年美债收益率位于过去3年低位，对估值相对友好"
    return "中立", "10年美债收益率位于过去3年中性区间"


def qqq_pe_signal(v):
    if v is None: return "中立", "纳斯达克100 Forward PE缺少数据"
    if v <= 22: return "偏买", "纳斯达克100 Forward PE偏低，估值相对便宜"
    if v >= 30: return "偏卖", "纳斯达克100 Forward PE偏高，估值相对偏贵"
    return "中立", "纳斯达克100 Forward PE处于中性区间"


def fetch_put_call():
    errors = []
    for back in range(11):
        d = date.today() - timedelta(days=back)
        try:
            text = html.unescape(re.sub(r"<[^>]+>", " ", get(f"https://www.cboe.com/us/options/market_statistics/daily/?dt={d.isoformat()}").text))
            m = re.search(r"EQUITY PUT/CALL RATIO\s+([0-9]+(?:\.[0-9]+)?)", re.sub(r"\s+", " ", text), re.I)
            if m:
                value = round(float(m.group(1)), 4); signal, explanation = put_call_signal(value)
                return {"value": value, "date": d.isoformat(), "source": "Cboe", "signal": signal, "explanation": explanation}
            errors.append(f"{d}: ratio not found")
        except Exception as exc: errors.append(f"{d}: {exc}")
    raise RuntimeError(" | ".join(errors[-3:]))


def fetch_fear_greed():
    item = get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata").json()["fear_and_greed"]
    ts = item.get("timestamp")
    if isinstance(ts, (int, float)): as_of = datetime.fromtimestamp(float(ts) / 1000).date().isoformat()
    elif isinstance(ts, str) and ts:
        try: as_of = datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
        except ValueError: as_of = date.today().isoformat()
    else: as_of = date.today().isoformat()
    value = round(float(item["score"]), 2); signal, explanation = fgi_signal(value)
    return {"value": value, "rating": str(item.get("rating", "")), "date": as_of, "source": "CNN Fear & Greed", "signal": signal, "explanation": explanation}


def plain_text(raw):
    raw = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def parse_aaii(text):
    text = text.replace("−", "-").replace("–", "-")
    current = re.search(
        r"This week.?s results\s+Week ending\s+([A-Za-z]+ \d{1,2}, \d{4})(.*?)(?:Cast your vote|Sentiment this week|Recent weekly results|$)",
        text,
        re.I | re.S,
    )
    if current:
        as_of = datetime.strptime(current.group(1), "%B %d, %Y").date()
        section = current.group(2)
        values = []
        for label in ["Bullish", "Neutral", "Bearish"]:
            found = re.search(rf"{label}\s+([0-9]+(?:\.[0-9]+)?)%", section, re.I)
            if not found: raise RuntimeError(f"AAII {label} value not found")
            values.append(round(float(found.group(1)), 2))
        bullish, neutral, bearish = values
    else:
        recent = re.search(
            r"Recent weekly results\s+Week Ending\s+Sentiment Votes\s+Bullish Neutral Bearish\s+"
            r"(\d{1,2}/\d{1,2}/\d{4})\s+([0-9]+(?:\.[0-9]+)?)%\s+"
            r"([0-9]+(?:\.[0-9]+)?)%\s+([0-9]+(?:\.[0-9]+)?)%",
            text,
            re.I | re.S,
        )
        if not recent: raise RuntimeError("AAII current survey results not found")
        as_of = datetime.strptime(recent.group(1), "%m/%d/%Y").date()
        bullish, neutral, bearish = [round(float(recent.group(i)), 2) for i in range(2, 5)]
    if not 99 <= bullish + neutral + bearish <= 101:
        raise RuntimeError("AAII sentiment percentages failed sum check")
    return as_of, bullish, neutral, bearish


def fetch_aaii():
    as_of, bullish, neutral, bearish = parse_aaii(plain_text(get(AAII_URL).text))
    age_days = (date.today() - as_of).days
    if age_days < 0 or age_days > 10:
        raise RuntimeError(f"AAII survey is stale or future-dated: {as_of.isoformat()} ({age_days} days old)")
    spread = round(bullish - bearish, 2); signal, explanation = aaii_signal(spread)
    return {"bullish": bullish, "neutral": neutral, "bearish": bearish, "bull_bear_spread": spread, "date": as_of.isoformat(), "frequency": "weekly", "source": "AAII Sentiment Survey", "source_url": AAII_URL, "signal": signal, "explanation": explanation}


def fetch_gold_copper():
    s = ratio_series("GC=F", "HG=F"); p1, p3, p5 = pct(s, 1), pct(s, 3), pct(s, 5); signal, explanation = gold_copper_signal(p3)
    return {"value": round(float(s.iloc[-1]), 4), "date": s.index[-1].date().isoformat(), "source": "Yahoo Finance GC=F / HG=F", "percentile_1y": p1, "percentile_3y": p3, "percentile_5y": p5, "signal": signal, "explanation": explanation, "note": "绝对值受期货报价单位影响，综合判断只使用历史百分位。"}


def fetch_treasury():
    raw = close_series("^TNX"); s = raw / 10 if float(raw.tail(60).median()) > 20 else raw
    p1, p3, p5 = pct(s, 1), pct(s, 3), pct(s, 5); signal, explanation = treasury_signal(p3)
    return {"value": round(float(s.iloc[-1]), 4), "unit": "percent", "date": s.index[-1].date().isoformat(), "source": "Yahoo Finance ^TNX", "percentile_1y": p1, "percentile_3y": p3, "percentile_5y": p5, "signal": signal, "explanation": explanation}


def _coverage(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(value) or value < 0:
        return None
    if value > 1.5:
        value /= 100.0
    return round(value, 4) if 0 <= value <= 1.0 else None


def _fetch_qqq_pe_once(market_date=None):
    df = pd.read_excel(BytesIO(get(PE_URL).content), engine="openpyxl")
    required = {
        "Date", "ETF", "PE Ratio", "Forward PE",
        "PE coverage", "Forward PE coverage",
    }
    missing = required.difference(df.columns)
    if missing:
        raise RuntimeError(f"PE history missing columns: {sorted(missing)}")

    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["ETF"] = df["ETF"].astype(str).str.upper().str.strip()
    for col in ["PE Ratio", "Forward PE", "PE coverage", "Forward PE coverage"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    rows = df[(df["ETF"] == "QQQ") & df["Date"].notna()].sort_values("Date")
    if rows.empty:
        raise RuntimeError("No QQQ rows found in ETF_PE_history.xlsx")

    # One coherent row only. Never mix a fresh trailing PE with an older forward PE.
    row = rows.iloc[-1]
    row_date = pd.Timestamp(row["Date"]).date()
    if market_date:
        expected = pd.Timestamp(market_date).date()
        if row_date < expected:
            raise RuntimeError(
                f"QQQ PE history is stale: latest={row_date.isoformat()}, market_date={expected.isoformat()}"
            )

    trailing_pe = num(row["PE Ratio"])
    forward_pe = num(row["Forward PE"])
    pe_coverage = _coverage(row["PE coverage"])
    forward_pe_coverage = _coverage(row["Forward PE coverage"])

    if trailing_pe is None or forward_pe is None:
        raise RuntimeError(
            f"Latest QQQ PE row {row_date.isoformat()} is missing trailing or forward PE"
        )
    if pe_coverage is None or pe_coverage < MIN_QQQ_PE_COVERAGE:
        raise RuntimeError(
            f"Latest QQQ trailing PE coverage is too low: {pe_coverage}"
        )
    if forward_pe_coverage is None or forward_pe_coverage < MIN_QQQ_PE_COVERAGE:
        raise RuntimeError(
            f"Latest QQQ forward PE coverage is too low: {forward_pe_coverage}"
        )

    row_date_text = row_date.isoformat()
    return {
        "nasdaq100": {
            "market": "纳斯达克100",
            "trailing_pe": trailing_pe,
            "forward_pe": forward_pe,
            "source_symbol": "QQQ",
            "is_etf_proxy": True,
            "pe_coverage": pe_coverage,
            "forward_pe_coverage": forward_pe_coverage,
            "pe_date": row_date_text,
            "forward_pe_date": row_date_text,
            "date": row_date_text,
            "source": "weekly-etf-report / ETF_PE_history.xlsx",
        }
    }


def fetch_qqq_pe(market_date=None, attempts=QQQ_PE_ATTEMPTS, retry_seconds=QQQ_PE_RETRY_SECONDS):
    """Wait briefly for the upstream ETF report, then fail closed if it is still stale."""
    last_error = None
    attempts = max(1, int(attempts))
    for attempt in range(1, attempts + 1):
        try:
            return _fetch_qqq_pe_once(market_date=market_date)
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            print(
                f"QQQ PE not ready (attempt {attempt}/{attempts}): {exc}. "
                f"Retrying in {retry_seconds}s..."
            )
            time.sleep(max(0, float(retry_seconds)))
    raise RuntimeError(f"QQQ PE unavailable after {attempts} attempt(s): {last_error}")


def safe(name, fn, errors, fallback):
    try: return fn()
    except Exception as exc: errors.append(f"{name}: {exc}"); return fallback


def _iso_date(value):
    if not value:
        return None
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def validate_publish_quality(market_date, vol, macro, valuation):
    """Block publication when too much of the market snapshot is missing or stale."""
    market_day = _iso_date(market_date)
    if market_day is None:
        raise RuntimeError("Market date is missing or invalid")

    toronto_today = datetime.now(ZoneInfo("America/Toronto")).date()
    market_age = (toronto_today - market_day).days
    if market_age < 0 or market_age > 4:
        raise RuntimeError(
            f"Market date is stale or future-dated: {market_day.isoformat()} "
            f"({market_age} days from Toronto today)"
        )

    qqq = valuation.get("nasdaq100", {})
    metrics = {
        "VIX": (vol.get("vix", {}).get("value"), vol.get("vix", {}).get("date"), 0),
        "VXN": (vol.get("vxn", {}).get("value"), vol.get("vxn", {}).get("date"), 1),
        "Equity Put/Call": (macro.get("equity_put_call", {}).get("value"), macro.get("equity_put_call", {}).get("date"), 4),
        "Fear & Greed": (macro.get("fear_greed", {}).get("value"), macro.get("fear_greed", {}).get("date"), 4),
        "AAII": (macro.get("aaii_sentiment", {}).get("bull_bear_spread"), macro.get("aaii_sentiment", {}).get("date"), 10),
        "Gold/Copper": (macro.get("gold_copper_ratio", {}).get("value"), macro.get("gold_copper_ratio", {}).get("date"), 4),
        "10Y Treasury": (macro.get("treasury_10y", {}).get("value"), macro.get("treasury_10y", {}).get("date"), 4),
        "QQQ Forward PE": (qqq.get("forward_pe"), qqq.get("forward_pe_date") or qqq.get("date"), 4),
    }

    available = {name: value is not None for name, (value, _date, _lag) in metrics.items()}
    required = ["VIX", "VXN", "10Y Treasury", "QQQ Forward PE"]
    missing_required = [name for name in required if not available[name]]
    if missing_required:
        raise RuntimeError("Missing required indicators: " + ", ".join(missing_required))

    available_count = sum(available.values())
    if available_count < MIN_AVAILABLE_INDICATORS:
        missing = [name for name, ok in available.items() if not ok]
        raise RuntimeError(
            f"Only {available_count}/{len(metrics)} indicators are valid; "
            f"minimum is {MIN_AVAILABLE_INDICATORS}. Missing: {', '.join(missing)}"
        )

    source_age_days = {}
    for name, (value, date_text, max_lag) in metrics.items():
        if value is None:
            continue
        source_day = _iso_date(date_text)
        if source_day is None:
            raise RuntimeError(f"{name} has a value but no valid source date")
        delta = (market_day - source_day).days
        source_age_days[name] = delta
        if abs(delta) > max_lag:
            raise RuntimeError(
                f"{name} is stale/incoherent: source={source_day.isoformat()}, "
                f"market={market_day.isoformat()}, delta={delta}d, allowed={max_lag}d"
            )

    pe_coverage = _coverage(qqq.get("pe_coverage"))
    fpe_coverage = _coverage(qqq.get("forward_pe_coverage"))
    if pe_coverage is None or pe_coverage < MIN_QQQ_PE_COVERAGE:
        raise RuntimeError(f"QQQ trailing PE coverage too low: {pe_coverage}")
    if fpe_coverage is None or fpe_coverage < MIN_QQQ_PE_COVERAGE:
        raise RuntimeError(f"QQQ forward PE coverage too low: {fpe_coverage}")

    return {
        "status": "pass",
        "available_count": available_count,
        "total_indicators": len(metrics),
        "minimum_required": MIN_AVAILABLE_INDICATORS,
        "required_indicators": required,
        "qqq_min_pe_coverage": MIN_QQQ_PE_COVERAGE,
        "source_age_days_vs_market_date": source_age_days,
    }


def overall(vol, macro, valuation):
    details = []
    for key in ["vix", "vxn"]:
        item = vol[key]; signal, reason = vol_signal(item["label"], item["percentile_3y"])
        details.append({"indicator": item["label"], "signal": signal, "reason": reason, "included": item["value"] is not None})
    for key, label in [("equity_put_call", "Equity Put/Call Ratio"), ("fear_greed", "Fear & Greed Index"), ("aaii_sentiment", "AAII Bull-Bear Spread"), ("gold_copper_ratio", "Gold / Copper Ratio"), ("treasury_10y", "10Y Treasury Yield")]:
        item = macro[key]; available = item.get("bull_bear_spread") is not None if key == "aaii_sentiment" else item.get("value") is not None
        details.append({"indicator": label, "signal": item["signal"], "reason": item["explanation"], "included": available})
    qqq = valuation["nasdaq100"]; signal, reason = qqq_pe_signal(qqq["forward_pe"])
    details.append({"indicator": "纳斯达克100 Forward PE", "signal": signal, "reason": reason, "included": qqq["forward_pe"] is not None})
    valid = [x for x in details if x["included"]]; buy = sum(x["signal"] == "偏买" for x in valid); neutral = sum(x["signal"] == "中立" for x in valid); sell = sum(x["signal"] == "偏卖" for x in valid); score = buy - sell
    return {"result": "偏买" if score >= 2 else "偏卖" if score <= -2 else "中立", "score": score, "buy_count": buy, "neutral_count": neutral, "sell_count": sell, "available_count": len(valid), "missing_count": len(details) - len(valid), "details": details, "method_note": "VIX、VXN、Put/Call、Fear & Greed、AAII及Gold/Copper采用反向情绪信号；10Y Treasury采用方向信号；估值只读取QQQ的PE与Forward PE。", "disclaimer": "仅供参考，不构成任何投资建议。"}


def main():
    errors, vol = [], {}
    for key, (symbol, label, market) in VOL.items():
        try:
            s = close_series(symbol)
            vol[key] = {"label": label, "market": market, "source_symbol": symbol, "value": round(float(s.iloc[-1]), 4), "percentile_1y": pct(s, 1), "percentile_3y": pct(s, 3), "percentile_5y": pct(s, 5), "date": s.index[-1].date().isoformat(), "source": "Yahoo Finance"}
        except Exception as exc:
            errors.append(f"{label} ({symbol}): {exc}"); vol[key] = {"label": label, "market": market, "source_symbol": symbol, "value": None, "percentile_1y": None, "percentile_3y": None, "percentile_5y": None, "date": "", "source": "Yahoo Finance"}
    if vol["vix"]["value"] is None: print("ERROR: VIX data is required.", file=sys.stderr); return 1
    macro = {
        "equity_put_call": safe("Equity Put/Call", fetch_put_call, errors, {"value": None, "date": "", "source": "Cboe", "signal": "中立", "explanation": "抓取失败"}),
        "fear_greed": safe("Fear & Greed", fetch_fear_greed, errors, {"value": None, "rating": "", "date": "", "source": "CNN Fear & Greed", "signal": "中立", "explanation": "抓取失败"}),
        "aaii_sentiment": safe("AAII Sentiment", fetch_aaii, errors, {"bullish": None, "neutral": None, "bearish": None, "bull_bear_spread": None, "date": "", "frequency": "weekly", "source": "AAII Sentiment Survey", "source_url": "", "signal": "中立", "explanation": "抓取失败"}),
        "gold_copper_ratio": safe("Gold/Copper", fetch_gold_copper, errors, {"value": None, "date": "", "source": "Yahoo Finance GC=F / HG=F", "percentile_1y": None, "percentile_3y": None, "percentile_5y": None, "signal": "中立", "explanation": "抓取失败"}),
        "treasury_10y": safe("10Y Treasury", fetch_treasury, errors, {"value": None, "unit": "percent", "date": "", "source": "Yahoo Finance ^TNX", "percentile_1y": None, "percentile_3y": None, "percentile_5y": None, "signal": "中立", "explanation": "抓取失败"}),
    }
    market_date = vol["vix"]["date"]
    valuation = safe(
        "QQQ PE history",
        lambda: fetch_qqq_pe(market_date=market_date),
        errors,
        {"nasdaq100": {"market": "纳斯达克100", "trailing_pe": None, "forward_pe": None, "source_symbol": "QQQ", "is_etf_proxy": True, "pe_coverage": None, "forward_pe_coverage": None, "pe_date": "", "forward_pe_date": "", "date": "", "source": "weekly-etf-report / ETF_PE_history.xlsx"}},
    )

    try:
        quality_gate = validate_publish_quality(market_date, vol, macro, valuation)
    except Exception as exc:
        errors.append(f"Publish quality gate: {exc}")
        print("ERROR: publication blocked by data-quality gate.", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1

    payload = {
        "market_date": market_date,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "volatility": vol,
        "macro": macro,
        "valuation": valuation,
        "overall_signal": overall(vol, macro, valuation),
        "quality_gate": quality_gate,
        "errors": errors,
    }
    out = Path(__file__).resolve().parent / "output"; out.mkdir(exist_ok=True); path = out / "latest_data.json"; path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2)); print(f"\nSaved to: {path}"); return 0


if __name__ == "__main__": raise SystemExit(main())
