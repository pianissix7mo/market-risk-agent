from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pandas as pd
import yfinance as yf


TICKERS = {
    "VIX": "^VIX",
    "VXN": "^VXN",
    "VIX3M": "^VIX3M",
}


def fetch_daily_close(symbol: str, period: str = "3y") -> pd.Series:
    """Download daily closes and return a clean, timezone-naive Series."""
    df = yf.Ticker(symbol).history(
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=False,
    )

    if df.empty or "Close" not in df.columns:
        raise RuntimeError(f"No price data returned for {symbol}")

    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if close.empty:
        raise RuntimeError(f"No valid closing prices returned for {symbol}")

    index = pd.to_datetime(close.index)
    try:
        index = index.tz_localize(None)
    except TypeError:
        pass
    close.index = index
    return close.sort_index()


def percentile_rank(series: pd.Series, value: float) -> float:
    """Percentage of observations less than or equal to value."""
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        raise ValueError("Cannot calculate percentile from an empty series")
    return float((clean <= value).mean() * 100)


def judgement(vix: float, ratio: float | None) -> str:
    if vix < 15:
        vix_text = "波动压力较低"
    elif vix < 20:
        vix_text = "波动压力温和"
    elif vix < 30:
        vix_text = "市场风险偏高"
    else:
        vix_text = "市场处于高压状态"

    if ratio is None:
        return vix_text
    if ratio >= 1:
        return f"{vix_text}；期限结构出现倒挂"
    if ratio >= 0.9:
        return f"{vix_text}；期限结构偏紧"
    return f"{vix_text}；期限结构正常"


def main() -> int:
    data: dict[str, pd.Series] = {}
    errors: list[str] = []

    for name, symbol in TICKERS.items():
        try:
            data[name] = fetch_daily_close(symbol)
        except Exception as exc:
            errors.append(f"{name} ({symbol}): {exc}")

    if "VIX" not in data:
        print("ERROR: VIX data is required.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    vix = data["VIX"]
    latest_date = vix.index[-1]
    latest_vix = float(vix.iloc[-1])
    vix_pct = percentile_rank(vix, latest_vix)

    latest_vxn = float(data["VXN"].iloc[-1]) if "VXN" in data else None
    ratio = None

    if "VIX3M" in data:
        combined = pd.concat(
            [data["VIX"].rename("VIX"), data["VIX3M"].rename("VIX3M")],
            axis=1,
            join="inner",
        ).dropna()
        combined = combined[combined["VIX3M"] != 0]
        if not combined.empty:
            ratio_series = combined["VIX"] / combined["VIX3M"]
            ratio = float(ratio_series.iloc[-1])

    rows = [
        ["VIX", f"{latest_vix:.2f}", f"P{vix_pct:.0f}", judgement(latest_vix, ratio)],
        [
            "VXN",
            f"{latest_vxn:.2f}" if latest_vxn is not None else "抓取失败",
            "—",
            "纳指波动压力参考",
        ],
        [
            "VIX/VIX3M",
            f"{ratio:.2f}" if ratio is not None else "抓取失败",
            "—",
            "期限结构正常" if ratio is not None and ratio < 1 else
            "期限结构倒挂" if ratio is not None else "暂无判断",
        ],
    ]

    title_date = latest_date.strftime("%Y-%m-%d")
    lines = [
        f"# 每日美股风险温度｜{title_date}",
        "",
        "| 指标 | 最新值 | 过去3年位置 | 判断 |",
        "|---|---:|---:|---|",
    ]
    for row in rows:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")

    if errors:
        lines.extend(["", "## 抓取提示"])
        lines.extend([f"- {error}" for error in errors])

    lines.extend([
        "",
        f"_生成时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}_",
        "",
        "> 说明：周末或休市日显示最近一个交易日的收盘数据。",
    ])

    report = "\n".join(lines) + "\n"
    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "latest_report.md"
    output_file.write_text(report, encoding="utf-8")

    print(report)
    print(f"Saved to: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
