from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
L, R = 72, 1008
COL = {
    "bg": "#07131F", "bg2": "#0C2136", "card": "#0F2032",
    "chip": "#091824", "line": "#274564", "text": "#F4F8FC",
    "muted": "#A9B9CA", "dim": "#7E90A5", "blue": "#63B3FF",
    "green": "#37D39A", "yellow": "#F5C85C", "red": "#FF6B72",
}
REGULAR = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]
BOLD = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]
Box = tuple[int, int, int, int]


def _pick(items: list[tuple[str, int]]) -> tuple[str, int]:
    for path, index in items:
        if Path(path).exists():
            return path, index
    raise RuntimeError("Install fonts-noto-cjk before generating media.")


REGULAR_FONT, BOLD_FONT = _pick(REGULAR), _pick(BOLD)


def ft(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path, index = BOLD_FONT if bold else REGULAR_FONT
    return ImageFont.truetype(path, size=size, index=index)


def num(value: Any, digits: int = 2, suffix: str = "") -> str:
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "--"


def pct(value: Any) -> str:
    try:
        numeric = float(value)
        # Keep normal percentile labels compact, but retain one decimal at
        # extreme tails so P1.19 is not misleadingly flattened to P1.
        return f"P{numeric:.1f}" if numeric < 5 or numeric > 95 else f"P{int(round(numeric))}"
    except (TypeError, ValueError):
        return "P--"


def sig_color(signal: str) -> str:
    return {"偏买": COL["green"], "中立": COL["yellow"], "偏卖": COL["red"]}.get(signal, COL["muted"])


class Validator:
    def __init__(self, page: str) -> None:
        self.page = page
        self.items: list[tuple[str, Box]] = []

    def add(self, name: str, actual: Box, allowed: Box) -> None:
        if not (allowed[0] <= actual[0] <= actual[2] <= allowed[2] and allowed[1] <= actual[1] <= actual[3] <= allowed[3]):
            raise AssertionError(f"{self.page}:{name} left box: {actual} not in {allowed}")
        for other_name, other in self.items:
            if not (actual[2] + 2 <= other[0] or other[2] + 2 <= actual[0] or actual[3] + 2 <= other[1] or other[3] + 2 <= actual[1]):
                raise AssertionError(f"{self.page}: overlap {name} {actual} / {other_name} {other}")
        self.items.append((name, actual))


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    return draw.textbbox((0, 0), text or " ", font=font)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for ch in str(text):
        if ch == "\n":
            lines.append(line)
            line = ""
            continue
        trial = line + ch
        box = _measure(draw, trial, font)
        if not line or box[2] - box[0] <= width:
            line = trial
        else:
            lines.append(line)
            line = ch
    if line or not lines:
        lines.append(line)
    return lines


def text(
    draw: ImageDraw.ImageDraw, v: Validator, name: str, box: Box, value: str,
    size: int, *, minimum: int = 15, bold: bool = False, fill: str | None = None,
    align: str = "left", valign: str = "top", gap: int = 5, max_lines: int | None = None,
) -> Box:
    width, height = box[2] - box[0], box[3] - box[1]
    fitted = None
    for s in range(size, minimum - 1, -1):
        font = ft(s, bold)
        lines = _wrap(draw, value, font, width)
        if max_lines is not None and len(lines) > max_lines:
            continue
        metrics = [_measure(draw, line, font) for line in lines]
        heights = [m[3] - m[1] for m in metrics]
        total = sum(heights) + gap * max(0, len(lines) - 1)
        if total <= height:
            fitted = font, lines, metrics, total
            break
    if fitted is None:
        raise ValueError(f"Text cannot fit {name}: {value!r}")
    font, lines, metrics, total = fitted
    y = box[1] if valign == "top" else box[1] + (height - total) // 2 if valign == "middle" else box[3] - total
    actual: list[Box] = []
    for line, m in zip(lines, metrics):
        w, h = m[2] - m[0], m[3] - m[1]
        x = box[0] if align == "left" else box[0] + (width - w) // 2 if align == "center" else box[2] - w
        draw.text((x - m[0], y - m[1]), line, font=font, fill=fill or COL["text"])
        actual.append((x, y, x + w, y + h))
        y += h + gap
    union = (min(a[0] for a in actual), min(a[1] for a in actual), max(a[2] for a in actual), max(a[3] for a in actual))
    v.add(name, union, box)
    return union


def bg() -> Image.Image:
    im = Image.new("RGB", (W, H), COL["bg"])
    d = ImageDraw.Draw(im)
    a = tuple(int(COL["bg"][i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(COL["bg2"][i:i + 2], 16) for i in (1, 3, 5))
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))
        d.line((0, y, W, y), fill=c)
    for x in range(0, W, 90):
        d.line((x, 0, x, H), fill="#17314A")
    for y in range(0, H, 100):
        d.line((0, y, W, y), fill="#17314A")
    return im


def card(im: Image.Image, box: Box, fill: str | None = None, outline: str | None = None, radius: int = 24) -> None:
    ImageDraw.Draw(im).rounded_rectangle(box, radius=radius, fill=fill or COL["card"], outline=outline or COL["line"], width=2)


def header(im: Image.Image, v: Validator, date: str, category: str) -> None:
    d = ImageDraw.Draw(im)
    text(d, v, "header-en", (120, 45, 960, 80), "MARKET RISK MONITOR", 24, bold=True, fill=COL["blue"], align="center", max_lines=1)
    text(d, v, "header-cn", (90, 92, 990, 158), "每日美股风险温度", 54, minimum=44, bold=True, align="center", max_lines=1)
    card(im, (334, 174, 746, 244), "#10263B", radius=18)
    text(d, v, "date", (350, 184, 730, 232), date, 38, minimum=30, bold=True, align="center", valign="middle", max_lines=1)
    card(im, (370, 262, 710, 326), "#0E2236", radius=18)
    text(d, v, "category", (390, 273, 690, 315), category, 27, minimum=21, bold=True, fill=COL["blue"], align="center", valign="middle", max_lines=1)
    d.line((120, 352, 960, 352), fill=COL["line"], width=2)
    d.line((420, 352, 660, 352), fill=COL["blue"], width=4)


def footer(im: Image.Image, v: Validator) -> None:
    d = ImageDraw.Draw(im)
    d.line((L, 1780, R, 1780), fill=COL["line"], width=2)
    text(d, v, "footer", (L, 1802, R, 1845), "仅供参考，不构成投资建议", 26, minimum=22, fill=COL["muted"], align="center", max_lines=1)


def pill(im: Image.Image, v: Validator, name: str, box: Box, signal: str) -> None:
    color = sig_color(signal)
    card(im, box, "#091521", color, 17)
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((x0 + 10, y0 + 10, x0 + 18, y1 - 10), radius=4, fill=color)
    text(d, v, name, (x0 + 28, y0 + 8, x1 - 10, y1 - 8), signal, 27, minimum=21, bold=True, fill=color, align="center", valign="middle", max_lines=1)


def vol_signal(value: Any) -> tuple[str, str]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "中立", "缺少过去3年分位数据"
    if x >= 75:
        return "偏买", "波动处于过去3年高位，反向信号偏买。"
    if x <= 25:
        return "偏卖", "波动处于过去3年低位，反向信号偏卖。"
    return "中立", "波动处于过去3年中性区间。"


def percentile_row(im: Image.Image, v: Validator, prefix: str, box: Box, data: dict[str, Any], color: str) -> None:
    d = ImageDraw.Draw(im)
    gap = 16
    w = (box[2] - box[0] - 2 * gap) // 3
    for i, (label, key) in enumerate((("过去1年", "percentile_1y"), ("过去3年", "percentile_3y"), ("过去5年", "percentile_5y"))):
        x0 = box[0] + i * (w + gap)
        x1 = x0 + w
        cell = (x0, box[1], x1, box[3])
        card(im, cell, COL["chip"], "#1D3852", 15)
        text(d, v, f"{prefix}-{key}-label", (x0 + 10, box[1] + 10, x1 - 10, box[1] + 40), label, 21, minimum=17, fill=COL["muted"], align="center", max_lines=1)
        value = data.get(key)
        text(d, v, f"{prefix}-{key}", (x0 + 10, box[1] + 45, x1 - 10, box[1] + 88), pct(value), 34, minimum=26, bold=True, fill=COL["blue"], align="center", max_lines=1)
        y0, y1 = box[3] - 28, box[3] - 16
        d.rounded_rectangle((x0 + 16, y0, x1 - 16, y1), radius=6, fill="#06101A")
        try:
            p = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            p = 0.0
        px = x0 + 16 + int((x1 - x0 - 32) * p / 100)
        d.rounded_rectangle((x0 + 16, y0, max(x0 + 22, px), y1), radius=6, fill=color)
        d.ellipse((px - 5, y0 + 1, px + 5, y1 - 1), fill="white")


def indicator(im: Image.Image, v: Validator, prefix: str, box: Box, title: str, subtitle: str, value: str, signal: str, data: dict[str, Any], note: str) -> None:
    card(im, box)
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    p = 34
    color = sig_color(signal)
    text(d, v, prefix + "-title", (x0 + p, y0 + 26, x1 - 220, y0 + 74), title, 40, minimum=28, bold=True, max_lines=1)
    pill(im, v, prefix + "-signal", (x1 - 194, y0 + 22, x1 - p, y0 + 80), signal)
    text(d, v, prefix + "-sub", (x0 + p, y0 + 82, x1 - p, y0 + 118), subtitle, 24, minimum=19, fill=COL["muted"], max_lines=1)
    card(im, (x0 + p, y0 + 135, x1 - p, y0 + 252), "#081623", "#1B3A55", 18)
    text(d, v, prefix + "-latest-label", (x0 + p + 18, y0 + 150, x0 + 220, y0 + 184), "最新值", 22, minimum=18, bold=True, fill=COL["muted"], max_lines=1)
    text(d, v, prefix + "-latest", (x0 + 210, y0 + 143, x1 - p - 20, y0 + 236), value, 72, minimum=45, bold=True, align="right", valign="middle", max_lines=1)
    text(d, v, prefix + "-history", (x0 + p, y0 + 272, x1 - p, y0 + 306), "历史分位", 23, minimum=19, bold=True, fill=color, max_lines=1)
    percentile_row(im, v, prefix, (x0 + p, y0 + 314, x1 - p, y0 + 430), data, color)
    text(d, v, prefix + "-note-label", (x0 + p, y0 + 452, x1 - p, y0 + 484), "简短判断", 21, minimum=17, bold=True, fill=COL["dim"], max_lines=1)
    text(d, v, prefix + "-note", (x0 + p, y0 + 494, x1 - p, y1 - 28), note, 25, minimum=18, fill=COL["muted"], max_lines=3)


def sentiment(im: Image.Image, v: Validator, prefix: str, box: Box, title: str, value: str, signal: str, note: str, extra: tuple[str, str] | None = None) -> None:
    card(im, box)
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    p = 32
    text(d, v, prefix + "-title", (x0 + p, y0 + 24, x1 - 218, y0 + 70), title, 34, minimum=25, bold=True, max_lines=1)
    pill(im, v, prefix + "-signal", (x1 - 190, y0 + 20, x1 - p, y0 + 76), signal)
    value_right = x1 - p
    if extra:
        value_right = x0 + 520
        card(im, (x0 + 548, y0 + 98, x1 - p, y0 + 198), COL["chip"], "#1D3852", 15)
        text(d, v, prefix + "-extra-label", (x0 + 566, y0 + 110, x1 - p - 18, y0 + 140), extra[0], 20, minimum=16, fill=COL["muted"], align="center", max_lines=1)
        text(d, v, prefix + "-extra", (x0 + 566, y0 + 145, x1 - p - 18, y0 + 184), extra[1], 29, minimum=22, bold=True, fill=COL["blue"], align="center", max_lines=1)
    text(d, v, prefix + "-value", (x0 + p, y0 + 94, value_right, y0 + 200), value, 76, minimum=52, bold=True, align="center", valign="middle", max_lines=1)
    text(d, v, prefix + "-note-label", (x0 + p, y0 + 222, x1 - p, y0 + 252), "判断", 20, minimum=17, bold=True, fill=COL["dim"], max_lines=1)
    text(d, v, prefix + "-note", (x0 + p, y0 + 262, x1 - p, y1 - 25), note, 24, minimum=17, fill=COL["muted"], max_lines=3)


def aaii(im: Image.Image, v: Validator, box: Box, data: dict[str, Any]) -> None:
    card(im, box)
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    p = 32
    signal = str(data.get("signal", "中立"))
    text(d, v, "aaii-title", (x0 + p, y0 + 24, x1 - 218, y0 + 70), "AAII Sentiment", 35, minimum=26, bold=True, max_lines=1)
    pill(im, v, "aaii-signal", (x1 - 190, y0 + 20, x1 - p, y0 + 76), signal)
    items = (("Bullish", num(data.get("bullish"), 1, "%")), ("Neutral", num(data.get("neutral"), 1, "%")), ("Bearish", num(data.get("bearish"), 1, "%")), ("Bull-Bear Spread", num(data.get("bull_bear_spread"), 1)))
    gx0, gy0, gx1, gy1 = x0 + p, y0 + 102, x1 - p, y0 + 342
    gap = 18
    cw = (gx1 - gx0 - gap) // 2
    ch = (gy1 - gy0 - gap) // 2
    for i, (label, value) in enumerate(items):
        row, col = divmod(i, 2)
        cx, cy = gx0 + col * (cw + gap), gy0 + row * (ch + gap)
        cell = (cx, cy, cx + cw, cy + ch)
        card(im, cell, COL["chip"], "#1D3852", 15)
        text(d, v, f"aaii-{i}-label", (cx + 14, cy + 13, cx + cw - 14, cy + 46), label, 21, minimum=16, fill=COL["muted"], align="center", max_lines=1)
        text(d, v, f"aaii-{i}", (cx + 14, cy + 49, cx + cw - 14, cy + ch - 14), value, 35, minimum=26, bold=True, align="center", valign="middle", max_lines=1)
    text(d, v, "aaii-note-label", (x0 + p, y0 + 365, x1 - p, y0 + 395), "判断", 20, minimum=17, bold=True, fill=COL["dim"], max_lines=1)
    text(d, v, "aaii-note", (x0 + p, y0 + 405, x1 - p, y1 - 24), str(data.get("explanation", "")), 24, minimum=17, fill=COL["muted"], max_lines=3)


def _save(im: Image.Image, v: Validator, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    im.save(output, quality=95)


def render_volatility(data: dict[str, Any], output: Path) -> None:
    im, v = bg(), Validator("01_volatility")
    header(im, v, str(data["market_date"]), "波动率")
    vx, vn = data["volatility"]["vix"], data["volatility"]["vxn"]
    sx, nx = vol_signal(vx.get("percentile_3y"))
    sn, nn = vol_signal(vn.get("percentile_3y"))
    indicator(im, v, "vix", (L, 386, R, 1000), "VIX", "标普500波动率", num(vx.get("value")), sx, vx, nx)
    indicator(im, v, "vxn", (L, 1028, R, 1642), "VXN", "纳斯达克100波动率", num(vn.get("value")), sn, vn, nn)
    footer(im, v)
    _save(im, v, output)


def render_sentiment(data: dict[str, Any], output: Path) -> None:
    im, v = bg(), Validator("02_sentiment")
    header(im, v, str(data["market_date"]), "市场情绪")
    m = data["macro"]
    pc, fg, aa = m["equity_put_call"], m["fear_greed"], m["aaii_sentiment"]
    sentiment(im, v, "put", (L, 386, R, 706), "Equity Put/Call", num(pc.get("value")), str(pc.get("signal", "中立")), str(pc.get("explanation", "")))
    rating = str(fg.get("rating", "")).strip().title() or "--"
    sentiment(im, v, "fear", (L, 730, R, 1064), "CNN Fear & Greed", num(fg.get("value")), str(fg.get("signal", "中立")), str(fg.get("explanation", "")), ("Rating", rating))
    aaii(im, v, (L, 1088, R, 1648), aa)
    footer(im, v)
    _save(im, v, output)


def render_macro(data: dict[str, Any], output: Path) -> None:
    im, v = bg(), Validator("03_macro")
    header(im, v, str(data["market_date"]), "宏观压力")
    m = data["macro"]
    gc, ty = m["gold_copper_ratio"], m["treasury_10y"]
    indicator(im, v, "gold", (L, 386, R, 1000), "Gold / Copper Ratio", "黄金 / 铜比", num(gc.get("value"), 2), str(gc.get("signal", "中立")), gc, str(gc.get("explanation", "")))
    indicator(im, v, "treasury", (L, 1028, R, 1642), "10Y Treasury Yield", "10年美债收益率", num(ty.get("value"), 3, "%"), str(ty.get("signal", "中立")), ty, str(ty.get("explanation", "")))
    footer(im, v)
    _save(im, v, output)


def qqq_signal(value: Any) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "中立"
    return "偏买" if x <= 22 else "偏卖" if x >= 30 else "中立"


def render_summary(data: dict[str, Any], output: Path) -> None:
    im, v = bg(), Validator("04_summary")
    header(im, v, str(data["market_date"]), "估值与综合判断")
    d = ImageDraw.Draw(im)
    o = data["overall_signal"]
    result = str(o.get("result", "中立"))
    color = sig_color(result)
    try:
        score = int(o.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    card(im, (L, 386, R, 758))
    text(d, v, "overall-label", (L + 34, 412, R - 210, 454), "Overall Signal", 28, minimum=22, bold=True, fill=color, max_lines=1)
    pill(im, v, "overall-pill", (R - 188, 404, R - 34, 462), result)
    text(d, v, "overall-result", (L + 34, 476, R - 34, 584), result, 108, minimum=78, bold=True, fill=color, align="center", valign="middle", max_lines=1)
    text(d, v, "overall-score", (L + 34, 590, R - 34, 632), f"综合分数 {score:+d}", 29, minimum=23, bold=True, fill=COL["muted"], align="center", max_lines=1)
    counts = (("买入指标", o.get("buy_count"), COL["green"]), ("中立指标", o.get("neutral_count"), COL["yellow"]), ("卖出指标", o.get("sell_count"), COL["red"]))
    gap = 14
    cw = (R - L - 68 - 2 * gap) // 3
    for i, (label, value, c) in enumerate(counts):
        x = L + 34 + i * (cw + gap)
        cell = (x, 650, x + cw, 724)
        card(im, cell, COL["chip"], "#1D3852", 15)
        text(d, v, f"count-{i}-label", (x + 8, 660, x + 155, 706), label, 20, minimum=15, bold=True, fill=COL["muted"], valign="middle", max_lines=1)
        text(d, v, f"count-{i}", (x + 160, 656, x + cw - 12, 712), str(value if value is not None else "--"), 36, minimum=27, bold=True, fill=c, align="right", valign="middle", max_lines=1)
    q = data["valuation"]["nasdaq100"]
    trail, forward, vs = num(q.get("trailing_pe"), 2, "x"), num(q.get("forward_pe"), 2, "x"), qqq_signal(q.get("forward_pe"))
    card(im, (L, 782, R, 1062))
    text(d, v, "valuation-title", (L + 34, 808, R - 34, 850), "QQQ 估值", 32, minimum=26, bold=True, align="center", max_lines=1)
    vals = ((L + 34, 518, "QQQ Trailing PE", trail, "当前估值", COL["text"]), (562, R - 34, "QQQ Forward PE", forward, vs, sig_color(vs)))
    for i, (x0, x1, label, value, foot, fc) in enumerate(vals):
        card(im, (x0, 872, x1, 1024), COL["chip"], "#1D3852", 15)
        text(d, v, f"val-{i}-label", (x0 + 14, 884, x1 - 14, 915), label, 22, minimum=16, fill=COL["muted"], align="center", max_lines=1)
        text(d, v, f"val-{i}", (x0 + 14, 920, x1 - 14, 980), value, 48, minimum=34, bold=True, align="center", valign="middle", max_lines=1)
        text(d, v, f"val-{i}-foot", (x0 + 14, 988, x1 - 14, 1014), foot, 21, minimum=16, bold=i == 1, fill=fc, align="center", max_lines=1)
    card(im, (L, 1086, R, 1738), "#10263C")
    text(d, v, "video-kicker", (L + 42, 1124, R - 42, 1170), "想知道这些指标怎么解读？", 31, minimum=24, bold=True, fill=COL["blue"], align="center", max_lines=1)
    text(d, v, "video-title", (L + 54, 1212, R - 54, 1372), "完整逻辑与使用方法\n请看我的解释视频", 54, minimum=38, bold=True, align="center", valign="middle", gap=14, max_lines=2)
    card(im, (L + 92, 1422, R - 92, 1510), COL["chip"], "#315777", 18)
    text(d, v, "video-cta", (L + 116, 1440, R - 116, 1492), "Market Risk Monitor 指标解析", 30, minimum=23, bold=True, fill=COL["blue"], align="center", valign="middle", max_lines=1)
    text(d, v, "video-topics", (L + 70, 1560, R - 70, 1610), "VIX · VXN · 市场情绪 · 宏观压力 · QQQ估值", 25, minimum=19, fill=COL["muted"], align="center", max_lines=1)
    text(d, v, "video-note", (L + 70, 1628, R - 70, 1698), "频道内搜索上方标题即可观看\n也可点击 Related Video 直接观看", 23, minimum=18, fill=COL["dim"], align="center", valign="middle", gap=8, max_lines=2)
    footer(im, v)
    _save(im, v, output)
