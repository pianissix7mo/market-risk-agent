from __future__ import annotations

from datetime import date, datetime, timedelta
from io import StringIO
import html
import json
from pathlib import Path
import re
import sys

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch
import pandas as pd
import requests
import yfinance as yf


VOL = {
    "VIX": ("^VIX", "标普500 · 30天波动率"),
    "VXN": ("^VXN", "纳指100 · 30天波动率"),
    "VIX3M": ("^VIX3M", "标普500 · 3个月波动率"),
}
HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/124 Safari/537.36"}
W, H, DPI = 1080, 1920, 120
BG, CARD, CARD2 = "#07111f", "#111f31", "#17283d"
TEXT, MUTED, BLUE = "#f3f6fb", "#9fb0c6", "#61a8ff"
BUY, MID, SELL, BORDER = "#35c98f", "#f0b44d", "#ef6a72", "#263a52"


def setup_font() -> None:
    names = ["Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei", "SimHei", "PingFang SC"]
    installed = {f.name: f.fname for f in font_manager.fontManager.ttflist}
    for name in names:
        if name in installed:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return
    paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in paths:
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=path).get_name()
            plt.rcParams["axes.unicode_minus"] = False
            return
    print("WARNING: no Chinese font found; text may render incorrectly", file=sys.stderr)


def get(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r


def fetch_close(symbol: str) -> pd.Series:
    df = yf.Ticker(symbol).history(period="5y", interval="1d", auto_adjust=False, actions=False)
    if df.empty or "Close" not in df:
        raise RuntimeError(f"No price data for {symbol}")
    s = pd.to_numeric(df["Close"], errors="coerce").dropna()
    idx = pd.to_datetime(s.index)
    try:
        idx = idx.tz_localize(None)
    except TypeError:
        pass
    s.index = idx
    return s.sort_index()


def pct(s: pd.Series, years: int) -> float:
    window = s[s.index >= s.index.max() - pd.DateOffset(years=years)]
    return float((window <= float(s.iloc[-1])).mean() * 100)


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
                return {"value": float(m.group(1)), "date": d.isoformat(), "source": "Cboe"}
            errors.append(f"{d}: not found")
        except Exception as e:
            errors.append(f"{d}: {e}")
    raise RuntimeError(" | ".join(errors[-3:]))


def fetch_baa() -> dict:
    frame = pd.read_csv(StringIO(get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAA10Y").text))
    frame["BAA10Y"] = pd.to_numeric(frame["BAA10Y"], errors="coerce")
    frame = frame.dropna(subset=["BAA10Y"])
    if frame.empty:
        raise RuntimeError("No FRED BAA10Y data")
    row = frame.iloc[-1]
    dc = "observation_date" if "observation_date" in frame else frame.columns[0]
    return {"value": float(row["BAA10Y"]), "date": str(row[dc]), "source": "FRED BAA10Y"}


def fetch_fgi() -> dict:
    d = get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata").json()["fear_and_greed"]
    ts = d.get("timestamp")
    as_of = datetime.fromtimestamp(float(ts) / 1000).date().isoformat() if ts else date.today().isoformat()
    return {"value": float(d["score"]), "date": as_of, "rating": str(d.get("rating", ""))}


def num(x) -> float | None:
    try:
        x = float(x)
        return x if x > 0 and pd.notna(x) else None
    except (TypeError, ValueError):
        return None


def fetch_pe(index_symbol: str, etf_symbol: str) -> dict:
    partial = None
    last_error = None
    for symbol, proxy in [(index_symbol, False), (etf_symbol, True)]:
        try:
            info = yf.Ticker(symbol).get_info()
            result = {"pe": num(info.get("trailingPE")), "fpe": num(info.get("forwardPE")), "symbol": symbol, "proxy": proxy}
            if result["pe"] is not None and result["fpe"] is not None:
                return result
            if partial is None and (result["pe"] is not None or result["fpe"] is not None):
                partial = result
        except Exception as e:
            last_error = e
    if partial:
        return partial
    raise RuntimeError(f"No PE data: {last_error}")


def safe(name: str, fn, errors: list[str], fallback: dict) -> dict:
    try:
        return fn()
    except Exception as e:
        errors.append(f"{name}: {e}")
        return fallback


def canvas(title: str, subtitle: str):
    fig, ax = plt.subplots(figsize=(W / DPI, H / DPI), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    ax.text(0.07, 0.945, title, fontsize=32, fontweight="bold", color=TEXT, va="top")
    ax.text(0.07, 0.907, subtitle, fontsize=15, color=MUTED, va="top")
    return fig, ax


def box(ax, x, y, w, h, color=CARD, edge=BORDER, lw=1.2, r=0.025):
    p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.012,rounding_size={r}", facecolor=color, edgecolor=edge, linewidth=lw)
    ax.add_patch(p)


def footer(ax, source: str, d: str):
    ax.text(0.07, 0.045, f"数据日期：{d}", fontsize=12, color=MUTED, va="bottom")
    ax.text(0.93, 0.045, source, fontsize=11, color=MUTED, ha="right", va="bottom")
    ax.text(0.5, 0.018, "周末或休市日显示最近可用数据", fontsize=10, color="#6f8198", ha="center", va="bottom")


def save(fig, path: Path):
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)


def page1(path: Path, vol: dict, d: str):
    fig, ax = canvas("美股波动温度", "VIX / VXN / VIX3M · 1年、3年、5年历史位置")
    for (name, item), y in zip(vol.items(), [0.68, 0.405, 0.13]):
        box(ax, 0.07, y, 0.86, 0.225)
        ax.text(0.105, y + 0.177, name, fontsize=27, fontweight="bold", color=TEXT, va="top")
        ax.text(0.105, y + 0.139, item["label"], fontsize=13.5, color=MUTED, va="top")
        value = f"{item['value']:.2f}" if item["value"] is not None else "N/A"
        ax.text(0.88, y + 0.176, value, fontsize=31, fontweight="bold", color=BLUE, ha="right", va="top")
        for i, (label, key) in enumerate([("1年", "p1"), ("3年", "p3"), ("5年", "p5")]):
            x = 0.105 + i * 0.255
            box(ax, x, y + 0.038, 0.215, 0.073, CARD2, r=0.016)
            v = item[key]
            ax.text(x + 0.02, y + 0.088, label, fontsize=11.5, color=MUTED, va="top")
            ax.text(x + 0.195, y + 0.084, f"P{v:.0f}" if v is not None else "—", fontsize=18, fontweight="bold", color=TEXT, ha="right", va="top")
    footer(ax, "Yahoo Finance", d)
    save(fig, path)


def put_text(v):
    return "抓取失败" if v is None else "防御情绪偏高" if v >= 0.9 else "情绪偏乐观" if v <= 0.55 else "情绪中性"


def baa_text(v):
    return "抓取失败" if v is None else "信用压力较高" if v >= 2.5 else "信用环境宽松" if v <= 1.5 else "信用市场稳定"


def fgi_text(v):
    if v is None: return "抓取失败"
    if v < 25: return "极度恐惧"
    if v < 45: return "恐惧"
    if v < 55: return "中立"
    if v < 75: return "贪婪"
    return "极度贪婪"


def page2(path: Path, pc: dict, baa: dict, fgi: dict, d: str):
    fig, ax = canvas("情绪与信用", "期权仓位、信用利差、恐惧贪婪指数")
    cards = [
        ("Equity Put/Call", pc, put_text(pc["value"]), "Cboe股票期权看跌/看涨成交量比"),
        ("Baa信用利差", baa, baa_text(baa["value"]), "Baa企业债收益率减去10年美债收益率"),
        ("FGI 恐惧贪婪", fgi, fgi_text(fgi["value"]), "0代表极度恐惧，100代表极度贪婪"),
    ]
    for (title, metric, judgement, explain), y in zip(cards, [0.68, 0.405, 0.13]):
        box(ax, 0.07, y, 0.86, 0.225)
        ax.text(0.105, y + 0.175, title, fontsize=24, fontweight="bold", color=TEXT, va="top")
        if metric["value"] is None:
            value = "N/A"
        elif title == "Baa信用利差":
            value = f"{metric['value']:.2f}%"
        elif title.startswith("FGI"):
            value = f"{metric['value']:.0f}/100"
        else:
            value = f"{metric['value']:.2f}"
        ax.text(0.88, y + 0.177, value, fontsize=31, fontweight="bold", color=BLUE, ha="right", va="top")
        ax.text(0.105, y + 0.115, judgement, fontsize=18, fontweight="bold", color=TEXT, va="top")
        ax.text(0.105, y + 0.068, explain, fontsize=12.5, color=MUTED, va="top")
        ax.text(0.88, y + 0.043, metric["date"], fontsize=10.5, color="#71839a", ha="right", va="top")
    footer(ax, "Cboe / FRED / CNN", d)
    save(fig, path)


def pe_text(v):
    return f"{v:.1f}x" if v is not None else "N/A"


def page3(path: Path, sp: dict, ndx: dict, d: str):
    fig, ax = canvas("美股估值", "标普500与纳指100 · 当前PE和Forward PE")
    for (name, data, fallback), y in zip(
        [("标普500", sp, "SPY"), ("纳指100", ndx, "QQQ")], [0.55, 0.22]
    ):
        box(ax, 0.07, y, 0.86, 0.27)
        ax.text(0.105, y + 0.218, name, fontsize=28, fontweight="bold", color=TEXT, va="top")
        tag = f"数据代码：{data['symbol']}" + ("（ETF代理）" if data["proxy"] else "")
        ax.text(0.88, y + 0.214, tag, fontsize=11, color=MUTED, ha="right", va="top")
        for x, label, value, color in [(0.105, "PE", data["pe"], TEXT), (0.545, "Forward PE", data["fpe"], BLUE)]:
            box(ax, x, y + 0.055, 0.35, 0.12, CARD2, r=0.018)
            ax.text(x + 0.025, y + 0.145, label, fontsize=13, color=MUTED, va="top")
            ax.text(x + 0.325, y + 0.128, pe_text(value), fontsize=26, fontweight="bold", color=color, ha="right", va="top")
        ax.text(0.105, y + 0.022, f"指数数据缺失时使用{fallback}代理", fontsize=10.5, color="#71839a", va="top")
    box(ax, 0.07, 0.115, 0.86, 0.065, "#0d1a29", r=0.016)
    ax.text(0.5, 0.147, "估值指标会随盈利预期变化，单独使用容易失真", fontsize=13.5, color=MUTED, ha="center", va="center")
    footer(ax, "Yahoo Finance", d)
    save(fig, path)


def signal(name: str, v: float | None) -> int:
    if v is None: return 0
    if name.startswith("P"): return 1 if v >= 75 else -1 if v <= 25 else 0
    if name == "pc": return 1 if v >= 0.9 else -1 if v <= 0.55 else 0
    if name == "baa": return 1 if v >= 2.5 else -1 if v <= 1.5 else 0
    if name == "fgi": return 1 if v <= 25 else -1 if v >= 75 else 0
    if name == "sp": return 1 if v <= 17 else -1 if v >= 22 else 0
    if name == "ndx": return 1 if v <= 22 else -1 if v >= 30 else 0
    return 0


def overall_signal(vol: dict, pc: dict, baa: dict, fgi: dict, sp: dict, ndx: dict):
    values = [
        signal("P1", vol["VIX"]["p3"]), signal("P2", vol["VXN"]["p3"]), signal("P3", vol["VIX3M"]["p3"]),
        signal("pc", pc["value"]), signal("baa", baa["value"]), signal("fgi", fgi["value"]),
        signal("sp", sp["fpe"]), signal("ndx", ndx["fpe"]),
    ]
    counts = {"偏买": values.count(1), "中立": values.count(0), "偏卖": values.count(-1)}
    score = sum(values)
    return ("偏买" if score >= 2 else "偏卖" if score <= -2 else "中立"), counts, score


def page4(path: Path, result: str, counts: dict, score: int, d: str):
    fig, ax = canvas("综合风险温度", "规则化信号 · 极端情绪采用反向解释")
    colors = {"偏买": BUY, "中立": MID, "偏卖": SELL}
    for label, x in zip(["偏买", "中立", "偏卖"], [0.07, 0.365, 0.66]):
        active = label == result
        box(ax, x, 0.68, 0.27, 0.145, colors[label] if active else CARD, colors[label] if active else BORDER, 2.2 if active else 1.2)
        c = BG if active else TEXT
        ax.text(x + 0.135, 0.772, label, fontsize=25, fontweight="bold", color=c, ha="center", va="center")
        ax.text(x + 0.135, 0.715, f"{counts[label]}项", fontsize=13, color=c if active else MUTED, ha="center", va="center")
    box(ax, 0.07, 0.52, 0.86, 0.11, CARD2)
    ax.text(0.105, 0.592, "当前结果", fontsize=13, color=MUTED, va="top")
    ax.text(0.105, 0.557, result, fontsize=29, fontweight="bold", color=colors[result], va="top")
    ax.text(0.88, 0.57, f"综合分数 {score:+d}", fontsize=16, color=TEXT, ha="right", va="center")
    box(ax, 0.07, 0.23, 0.86, 0.245)
    ax.text(0.105, 0.425, "指标解释", fontsize=20, fontweight="bold", color=TEXT, va="top")
    for i, line in enumerate([
        "波动与情绪：极端恐慌偏买，极端乐观偏卖",
        "期权与信用：防御过高偏买，过度平静偏卖",
        "估值：Forward PE偏低加分，偏高减分",
    ]):
        ax.text(0.105, 0.375 - i * 0.052, line, fontsize=13.2, color=MUTED, va="top")
    box(ax, 0.07, 0.12, 0.86, 0.07, "#152033", r=0.018)
    ax.text(0.5, 0.155, "指标解释与计算方法，详情请看解释视频", fontsize=14, color=TEXT, ha="center", va="center")
    ax.text(0.5, 0.082, "仅供参考，不构成任何投资建议", fontsize=14, fontweight="bold", color=SELL, ha="center", va="center")
    footer(ax, "自动生成", d)
    save(fig, path)


def main() -> int:
    setup_font()
    out = Path(__file__).resolve().parent / "output"
    out.mkdir(exist_ok=True)
    errors: list[str] = []
    vol = {}
    for name, (symbol, label) in VOL.items():
        try:
            s = fetch_close(symbol)
            vol[name] = {"label": label, "value": float(s.iloc[-1]), "date": s.index[-1].date().isoformat(), "p1": pct(s, 1), "p3": pct(s, 3), "p5": pct(s, 5)}
        except Exception as e:
            errors.append(f"{name}: {e}")
            vol[name] = {"label": label, "value": None, "date": "—", "p1": None, "p3": None, "p5": None}
    if vol["VIX"]["value"] is None:
        print("ERROR: VIX data is required", file=sys.stderr)
        return 1
    d = vol["VIX"]["date"]
    pc = safe("Cboe Put/Call", fetch_put_call, errors, {"value": None, "date": "—"})
    baa = safe("FRED BAA10Y", fetch_baa, errors, {"value": None, "date": "—"})
    fgi = safe("CNN FGI", fetch_fgi, errors, {"value": None, "date": "—", "rating": ""})
    sp = safe("S&P 500 PE", lambda: fetch_pe("^GSPC", "SPY"), errors, {"pe": None, "fpe": None, "symbol": "^GSPC", "proxy": False})
    ndx = safe("Nasdaq 100 PE", lambda: fetch_pe("^NDX", "QQQ"), errors, {"pe": None, "fpe": None, "symbol": "^NDX", "proxy": False})
    result, counts, score = overall_signal(vol, pc, baa, fgi, sp, ndx)

    page1(out / "short_01_volatility.png", vol, d)
    page2(out / "short_02_sentiment_credit.png", pc, baa, fgi, d)
    page3(out / "short_03_valuation.png", sp, ndx, d)
    page4(out / "short_04_signal.png", result, counts, score, d)

    snapshot = {"date": d, "volatility": vol, "put_call": pc, "baa_spread": baa, "fgi": fgi, "sp500": sp, "nasdaq100": ndx, "signal": {"result": result, "counts": counts, "score": score}, "errors": errors}
    (out / "latest_data.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    report = [f"# 每日美股风险温度｜{d}", "", f"综合结果：**{result}**", "", "输出：", "- short_01_volatility.png", "- short_02_sentiment_credit.png", "- short_03_valuation.png", "- short_04_signal.png", "", "> 指标解释与计算方法，详情请看解释视频。仅供参考，不构成任何投资建议。"]
    if errors:
        report += ["", "## 抓取提示"] + [f"- {e}" for e in errors]
    (out / "latest_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"Generated 4 vertical 1080x1920 images in {out}")
    for p in sorted(out.glob("short_*.png")):
        print(f"- {p}")
    for e in errors:
        print(f"WARNING: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
