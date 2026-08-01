from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1920

C = {
    "bg": "#06101D",
    "bg2": "#08182B",
    "panel": "#0C1A2B",
    "panel2": "#11243A",
    "border": "#2A87D8",
    "grid": "#0D2A46",
    "text": "#F5F9FF",
    "muted": "#A9BED4",
    "dim": "#6D879F",
    "blue": "#49B4FF",
    "blue2": "#84D8FF",
    "green": "#4CFF87",
    "yellow": "#FFD53D",
    "red": "#FF5757",
    "cyan": "#3CEBFF",
}

REGULAR_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
BOLD_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def first_existing(paths: list[str]) -> str:
    for path in paths:
        if Path(path).exists():
            return path
    raise RuntimeError("No suitable font found. Install fonts-noto-cjk.")


REGULAR_FONT = first_existing(REGULAR_CANDIDATES)
BOLD_FONT = first_existing(BOLD_CANDIDATES)


def f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(BOLD_FONT if bold else REGULAR_FONT, size=size)


def signal_color(signal: str) -> str:
    return {
        "偏买": C["green"],
        "中立": C["yellow"],
        "偏卖": C["red"],
    }.get(signal, C["muted"])


def safe_num(x: Any, digits: int = 2) -> str:
    if x is None:
        return "--"
    try:
        return f"{float(x):.{digits}f}"
    except Exception:
        return "--"


def safe_pct_rank(x: Any) -> str:
    if x is None:
        return "P--"
    try:
        return f"P{int(round(float(x)))}"
    except Exception:
        return "P--"


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_w: int, start: int, min_size: int = 20, bold: bool = False):
    for size in range(start, min_size - 1, -2):
        font = f(size, bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_w:
            return font
    return f(min_size, bold)


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int = 28, fill: str | None = None,
            outline: str | None = None, width: int = 2) -> None:
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=fill or C["panel"],
        outline=outline or C["border"],
        width=width,
    )


def draw_glow_text(base: Image.Image, xy: tuple[int, int], text: str, font: ImageFont.FreeTypeFont,
                   fill: str, glow: str | None = None, anchor: str | None = None) -> None:
    glow = glow or fill
    glow_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    for r, alpha in [(18, 70), (9, 110)]:
        gd.text(xy, text, font=font, fill=hex_to_rgba(glow, alpha), anchor=anchor)
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=r))
    base.alpha_composite(glow_layer)
    d = ImageDraw.Draw(base)
    d.text(xy, text, font=font, fill=fill, anchor=anchor)


def hex_to_rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (255, 255, 255, alpha)
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4)) + (alpha,)


def neon_box(base: Image.Image, box: tuple[int, int, int, int], glow_color: str, fill: str | None = None,
             radius: int = 28, line_color: str | None = None, line_width: int = 2) -> None:
    fill = fill or C["panel"]
    line_color = line_color or glow_color

    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)

    for w, a in [(16, 45), (10, 70), (6, 110)]:
        gd.rounded_rectangle(box, radius=radius, outline=hex_to_rgba(glow_color, a), width=w)

    glow = glow.filter(ImageFilter.GaussianBlur(radius=10))
    base.alpha_composite(glow)

    d = ImageDraw.Draw(base)
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=line_color, width=line_width)


def make_canvas() -> Image.Image:
    img = Image.new("RGBA", (WIDTH, HEIGHT), C["bg"])
    draw = ImageDraw.Draw(img)

    # background grid
    for x in range(0, WIDTH, 40):
        draw.line((x, 0, x, HEIGHT), fill=hex_to_rgba(C["grid"], 70), width=1)
    for y in range(0, HEIGHT, 40):
        draw.line((0, y, WIDTH, y), fill=hex_to_rgba(C["grid"], 70), width=1)

    # top glow
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((250, 90, 830, 260), fill=hex_to_rgba(C["blue"], 45))
    gd.ellipse((350, 120, 730, 220), fill=hex_to_rgba(C["cyan"], 35))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=40))
    img.alpha_composite(glow)
    return img


def draw_top_header(base: Image.Image, page_text: str, date_text: str) -> None:
    d = ImageDraw.Draw(base)

    draw_glow_text(base, (540, 70), "Daily Market Risk", f(30, False), C["blue2"], C["blue"], anchor="ma")
    title_font = fit_font(d, "每日市场风险温度", 900, 106, 72, True)
    draw_glow_text(base, (540, 150), "每日市场风险温度", title_font, C["text"], C["blue"], anchor="ma")

    # decorative lines
    d.line((70, 78, 380, 78), fill=C["blue"], width=2)
    d.line((700, 78, 1010, 78), fill=C["blue"], width=2)
    d.polygon([(270, 60), (300, 60), (320, 78), (290, 78)], fill=C["blue"])
    d.polygon([(760, 60), (790, 60), (770, 78), (740, 78)], fill=C["blue"])

    d.text((120, 280), f"📅 {date_text}", font=f(28), fill=C["muted"])
    d.text((590, 280), f"📄 {page_text}", font=f(28), fill=C["muted"])


def draw_footer(base: Image.Image, source: str) -> None:
    d = ImageDraw.Draw(base)
    d.line((80, 1830, 1000, 1830), fill=hex_to_rgba(C["grid"], 130), width=2)
    d.text((85, 1860), f"🗂 数据来源：{source}", font=f(23), fill=C["muted"])
    d.text((995, 1860), "🛡 仅供参考，不构成任何投资建议", font=f(23), fill=C["muted"], anchor="ra")


def draw_badge(base: Image.Image, box: tuple[int, int, int, int], text: str, color: str) -> None:
    neon_box(base, box, glow_color=color, fill=C["panel"], radius=24, line_color=color, line_width=3)
    draw_glow_text(base, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), text, f(52, True), color, color, anchor="mm")


def draw_rank_box(base: Image.Image, x: int, y: int, label: str, value: str, color: str) -> None:
    neon_box(base, (x, y, x + 270, y + 110), glow_color=color, fill=C["panel2"], radius=20, line_color=color, line_width=2)
    d = ImageDraw.Draw(base)
    d.text((x + 135, y + 24), label, font=f(22), fill=C["muted"], anchor="ma")
    draw_glow_text(base, (x + 135, y + 74), value, f(46, True), color, color, anchor="ma")


def draw_simple_line_chart(base: Image.Image, box: tuple[int, int, int, int], values: list[float], line_color: str) -> None:
    d = ImageDraw.Draw(base)
    x0, y0, x1, y1 = box

    # bands
    mid1 = y0 + int((y1 - y0) * 0.33)
    mid2 = y0 + int((y1 - y0) * 0.66)
    d.line((x0, y0, x1, y0), fill=hex_to_rgba(C["red"], 160), width=2)
    d.line((x0, mid1, x1, mid1), fill=hex_to_rgba(C["yellow"], 160), width=2)
    d.line((x0, mid2, x1, mid2), fill=hex_to_rgba(C["yellow"], 120), width=1)
    d.line((x0, y1, x1, y1), fill=hex_to_rgba(C["blue2"], 160), width=2)

    # labels
    d.text((x0 - 8, y0 - 4), "高位", font=f(17), fill=C["red"], anchor="ra")
    d.text((x0 - 8, mid1 - 10), "中性", font=f(17), fill=C["yellow"], anchor="ra")
    d.text((x0 - 8, y1 - 15), "低位", font=f(17), fill=C["blue2"], anchor="ra")

    if not values:
        return

    vmin = min(values)
    vmax = max(values)
    if abs(vmax - vmin) < 1e-9:
        vmax += 1
        vmin -= 1

    points = []
    for i, v in enumerate(values):
        x = x0 + (x1 - x0) * i / max(1, len(values) - 1)
        norm = (v - vmin) / (vmax - vmin)
        y = y1 - norm * (y1 - y0)
        points.append((x, y))

    # glow
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for width, alpha in [(8, 70), (4, 120)]:
        gd.line(points, fill=hex_to_rgba(line_color, alpha), width=width)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=4))
    base.alpha_composite(glow)

    d = ImageDraw.Draw(base)
    d.line(points, fill=line_color, width=3)
    px, py = points[-1]
    d.ellipse((px - 10, py - 10, px + 10, py + 10), outline=line_color, width=4, fill=C["panel"])
    d.ellipse((px - 4, py - 4, px + 4, py + 4), fill=C["text"])


def make_spark_values(seed: int, trend: float = 0.0, n: int = 70) -> list[float]:
    vals = []
    cur = 50 + seed * 0.3
    for i in range(n):
        cur += math.sin((i + seed) / 4.8) * 2.1 + trend + math.cos((i + seed) / 2.7) * 0.8
        vals.append(cur)
    return vals


def parse_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_volatility(data: dict[str, Any], output: Path) -> None:
    base = make_canvas()
    draw_top_header(base, "第1页 / 波动", data["market_date"])
    d = ImageDraw.Draw(base)

    vix = data["volatility"]["vix"]
    vxn = data["volatility"]["vxn"]

    # Card 1
    neon_box(base, (55, 350, 1025, 1030), glow_color=C["blue"])
    d.text((105, 400), "VIX", font=f(72, True), fill=C["blue"])
    d.text((310, 418), " |  标普500波动率", font=f(42, True), fill=C["text"])
    draw_glow_text(base, (105, 540), safe_num(vix.get("value")), f(138, True), C["text"], C["blue"])
    draw_badge(base, (700, 480, 965, 620), vix.get("signal", "中立"), signal_color(vix.get("signal", "中立")))
    draw_rank_box(base, 100, 670, "1年分位", safe_pct_rank(vix.get("percentile_1y")), C["blue"])
    draw_rank_box(base, 405, 670, "3年分位", safe_pct_rank(vix.get("percentile_3y")), C["blue"])
    draw_rank_box(base, 710, 670, "5年分位", safe_pct_rank(vix.get("percentile_5y")), C["blue"])
    draw_simple_line_chart(base, (170, 830, 965, 920), make_spark_values(1, 0.05), C["blue"])
    d.text((540, 960), "过去3年中性区间", font=f(24), fill=C["muted"], anchor="ma")

    # Card 2
    sig2 = "偏买" if float(vxn.get("percentile_3y") or 0) >= 75 else "偏卖" if float(vxn.get("percentile_3y") or 100) <= 25 else "中立"
    vxn_signal = vxn.get("signal", sig2)

    neon_box(base, (55, 1080, 1025, 1760), glow_color=C["green"])
    d.text((105, 1130), "VXN", font=f(72, True), fill=C["blue"])
    d.text((310, 1148), " |  纳指100波动率", font=f(42, True), fill=C["text"])
    draw_glow_text(base, (105, 1270), safe_num(vxn.get("value")), f(138, True), C["text"], C["green"])
    draw_badge(base, (700, 1210, 965, 1350), vxn_signal, signal_color(vxn_signal))
    draw_rank_box(base, 100, 1400, "1年分位", safe_pct_rank(vxn.get("percentile_1y")), C["green"])
    draw_rank_box(base, 405, 1400, "3年分位", safe_pct_rank(vxn.get("percentile_3y")), C["green"])
    draw_rank_box(base, 710, 1400, "5年分位", safe_pct_rank(vxn.get("percentile_5y")), C["green"])
    draw_simple_line_chart(base, (170, 1560, 965, 1650), make_spark_values(6, 0.25), C["green"])
    d.text((540, 1690), "过去3年高位，反向信号偏买", font=f(24), fill=C["green"], anchor="ma")

    draw_footer(base, "Yahoo Finance")
    base.convert("RGB").save(output)


def render_sentiment(data: dict[str, Any], output: Path) -> None:
    base = make_canvas()
    draw_top_header(base, "第2页 / 情绪", data["market_date"])
    d = ImageDraw.Draw(base)

    pc = data["macro"]["equity_put_call"]
    fg = data["macro"]["fear_greed"]
    aaii = data["macro"]["aaii_sentiment"]

    # Put/Call
    neon_box(base, (55, 350, 1025, 760), glow_color=C["blue"])
    d.text((105, 410), "Equity ", font=f(28, False), fill=C["blue"])
    d.text((275, 390), "Put/Call Ratio", font=f(54, True), fill=C["text"])
    draw_glow_text(base, (365, 520), safe_num(pc.get("value")), f(108, True), C["text"], C["blue"], anchor="ma")
    draw_badge(base, (760, 470, 965, 600), pc.get("signal", "中立"), signal_color(pc.get("signal", "中立")))
    d.text((300, 630), f"🕒 数据来源：Cboe", font=f(22), fill=C["muted"])
    d.text((660, 630), f"📅 {pc.get('date', '')}", font=f(22), fill=C["muted"])
    neon_box(base, (120, 680, 945, 735), glow_color=C["blue"], fill="#081726", radius=16, line_color=C["border"])
    d.text((170, 692), pc.get("explanation", "Put/Call处于中性区间"), font=f(22), fill=C["muted"])

    # Fear & Greed
    neon_box(base, (55, 790, 1025, 1200), glow_color=C["blue"])
    # gauge
    d.pieslice((100, 860, 370, 1130), start=180, end=360, fill=None, outline=C["muted"], width=6)
    segments = [
        (180, 216, "#D52B2B"),
        (216, 252, "#FF8A2A"),
        (252, 288, "#E6D140"),
        (288, 324, "#9BCB52"),
        (324, 360, "#41B96C"),
    ]
    for a0, a1, col in segments:
        d.arc((100, 860, 370, 1130), start=a0, end=a1, fill=col, width=18)
    val = float(fg.get("value") or 0)
    angle = 180 + val * 1.8
    cx, cy, r = 235, 995, 118
    px = cx + math.cos(math.radians(angle)) * r
    py = cy + math.sin(math.radians(angle)) * r
    d.line((cx, cy, px, py), fill=C["yellow"], width=5)
    d.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=C["yellow"])
    d.text((235, 1015), safe_num(val), font=f(62, True), fill=C["text"], anchor="ma")
    d.text((235, 1080), str(fg.get("rating", "")).capitalize(), font=f(28, True), fill=C["yellow"], anchor="ma")
    d.text((92, 1115), "0", font=f(20), fill=C["blue2"])
    d.text((350, 1115), "100", font=f(20), fill=C["blue2"], anchor="ra")

    d.text((430, 860), "Fear & Greed Index", font=f(52, True), fill=C["text"])
    draw_badge(base, (760, 930, 965, 1060), fg.get("signal", "中立"), signal_color(fg.get("signal", "中立")))
    d.text((430, 1030), "🕒 数据来源：CNN", font=f(22), fill=C["muted"])
    d.text((760, 1030), f"📅 {fg.get('date', '')}", font=f(22), fill=C["muted"])
    neon_box(base, (120, 1120, 945, 1175), glow_color=C["blue"], fill="#081726", radius=16, line_color=C["border"])
    d.text((170, 1132), fg.get("explanation", "恐惧贪婪指数处于中性区间"), font=f(22), fill=C["muted"])

    # AAII
    neon_box(base, (55, 1230, 1025, 1760), glow_color=C["green"])
    d.text((105, 1290), "AAII", font=f(70, True), fill=C["text"])
    d.text((315, 1297), "Bull-Bear Spread", font=f(54, True), fill=C["text"])
    d.ellipse((95, 1385, 310, 1600), outline=C["green"], width=5)
    d.text((202, 1480), "🐂  VS  🐻", font=f(40, True), fill=C["cyan"], anchor="ma")

    # metric boxes
    small_box(base, 365, 1400, 140, 130, "Bullish", f"{safe_num(aaii.get('bullish'), 1)}%", C["green"])
    small_box(base, 520, 1400, 140, 130, "Neutral", f"{safe_num(aaii.get('neutral'), 1)}%", C["blue2"])
    small_box(base, 675, 1400, 140, 130, "Bearish", f"{safe_num(aaii.get('bearish'), 1)}%", C["red"])
    small_box(base, 835, 1400, 140, 130, "Spread", safe_num(aaii.get("bull_bear_spread"), 1), C["green"])

    draw_badge(base, (760, 1560, 965, 1685), aaii.get("signal", "中立"), signal_color(aaii.get("signal", "中立")))
    d.text((400, 1565), "🕒 数据来源：AAII", font=f(22), fill=C["muted"])
    d.text((400, 1602), f"📅 {aaii.get('date', '')}", font=f(22), fill=C["muted"])
    neon_box(base, (100, 1688, 965, 1738), glow_color=C["green"], fill="#0B1F17", radius=16, line_color=C["green"])
    exp = aaii.get("explanation", "AAII悲观情绪明显高于乐观情绪，反向信号偏买")
    d.text((130, 1698), exp, font=f(20), fill=C["green"])

    draw_footer(base, "Cboe / CNN / AAII")
    base.convert("RGB").save(output)


def small_box(base: Image.Image, x: int, y: int, w: int, h: int, title: str, value: str, color: str):
    neon_box(base, (x, y, x + w, y + h), glow_color=color, fill=C["panel2"], radius=18, line_color=color, line_width=2)
    d = ImageDraw.Draw(base)
    d.text((x + 18, y + 18), title, font=f(18), fill=color)
    d.text((x + w // 2, y + 72), value, font=f(28, True), fill=C["text"], anchor="ma")


def render_macro(data: dict[str, Any], output: Path) -> None:
    base = make_canvas()
    draw_top_header(base, "第3页 / 宏观", data["market_date"])
    d = ImageDraw.Draw(base)

    gc = data["macro"]["gold_copper_ratio"]
    ty = data["macro"]["treasury_10y"]

    # Gold/Copper
    neon_box(base, (55, 350, 1025, 1030), glow_color=C["blue"])
    d.text((105, 400), "黄金/铜比", font=f(64, True), fill=C["blue"])
    d.text((465, 418), " |  Gold / Copper Ratio", font=f(32, True), fill=C["text"])
    draw_glow_text(base, (105, 540), safe_num(gc.get("value"), 3), f(122, True), C["text"], C["blue"])
    draw_badge(base, (700, 480, 965, 620), gc.get("signal", "中立"), signal_color(gc.get("signal", "中立")))
    draw_rank_box(base, 100, 670, "1年分位", safe_pct_rank(gc.get("percentile_1y")), C["blue"])
    draw_rank_box(base, 405, 670, "3年分位", safe_pct_rank(gc.get("percentile_3y")), C["blue"])
    draw_rank_box(base, 710, 670, "5年分位", safe_pct_rank(gc.get("percentile_5y")), C["blue"])
    draw_simple_line_chart(base, (170, 830, 965, 920), make_spark_values(12, 0.0), C["blue"])
    d.text((115, 960), f"📅 {gc.get('date', '')}", font=f(22), fill=C["muted"])
    d.text((420, 960), "◎ 黄金/铜比位于过去3年中性区间", font=f(22), fill=C["muted"])
    note = gc.get("note", "绝对值受期货报价单位影响，综合判断只使用历史百分位。")
    note_font = fit_font(d, note, 860, 21, 16)
    d.text((105, 1000), note, font=note_font, fill=C["dim"])

    # 10Y Treasury
    neon_box(base, (55, 1080, 1025, 1760), glow_color=C["red"])
    d.text((105, 1130), "10年美债收益率", font=f(66, True), fill=C["blue"])
    d.text((700, 1148), " |  10Y Treasury Yield", font=f(32, True), fill=C["text"], anchor="ma")
    draw_glow_text(base, (105, 1270), safe_num(ty.get("value"), 3) + "%", f(122, True), C["text"], C["red"])
    draw_badge(base, (700, 1210, 965, 1350), ty.get("signal", "偏卖"), signal_color(ty.get("signal", "偏卖")))
    draw_rank_box(base, 100, 1400, "1年分位", safe_pct_rank(ty.get("percentile_1y")), C["red"])
    draw_rank_box(base, 405, 1400, "3年分位", safe_pct_rank(ty.get("percentile_3y")), C["red"])
    draw_rank_box(base, 710, 1400, "5年分位", safe_pct_rank(ty.get("percentile_5y")), C["red"])
    draw_simple_line_chart(base, (170, 1560, 965, 1650), make_spark_values(19, 0.25), C["red"])
    d.text((115, 1690), f"📅 {ty.get('date', '')}", font=f(22), fill=C["muted"])
    d.text((420, 1690), ty.get("explanation", "10年美债收益率位于过去3年高位，对估值偏不利"), font=f(22), fill=C["muted"])

    draw_footer(base, "Yahoo Finance")
    base.convert("RGB").save(output)


def render_summary(data: dict[str, Any], output: Path) -> None:
    base = make_canvas()
    draw_top_header(base, "第4页 / 总结", data["market_date"])
    d = ImageDraw.Draw(base)

    overall = data["overall_signal"]
    qqq = data["valuation"]["nasdaq100"]

    result = overall.get("result", "中立")
    score = overall.get("score", 0)
    buy = overall.get("buy_count", 0)
    neutral = overall.get("neutral_count", 0)
    sell = overall.get("sell_count", 0)
    result_color = signal_color(result)

    # Top summary
    neon_box(base, (55, 350, 1025, 790), glow_color=result_color)
    d.text((105, 405), "今日市场风险温度", font=f(52, True), fill=C["blue"])
    draw_glow_text(base, (105, 505), result, f(148, True), result_color, result_color)
    draw_glow_text(base, (470, 515), f"{score:+d}", f(132, True), result_color, result_color)

    # meter
    meter_arc(base, (710, 450, 975, 720), score)

    # counts
    count_chip(base, (100, 670, 360, 760), f"偏买 {buy}", C["green"])
    count_chip(base, (410, 670, 670, 760), f"中立 {neutral}", C["yellow"])
    count_chip(base, (720, 670, 980, 760), f"偏卖 {sell}", C["red"])

    # QQQ valuation
    neon_box(base, (55, 830, 1025, 1120), glow_color=C["blue"])
    d.text((95, 870), "📊 QQQ 估值速览", font=f(42, True), fill=C["blue"])
    neon_box(base, (80, 940, 995, 1060), glow_color=C["blue"], fill=C["panel2"], radius=22, line_color=C["border"])
    d.text((130, 970), "QQQ PE", font=f(24), fill=C["muted"])
    d.text((130, 1014), f"{safe_num(qqq.get('trailing_pe'))}x", font=f(56, True), fill=C["blue"])
    d.line((350, 958, 350, 1038), fill=C["border"], width=2)
    d.text((410, 970), "QQQ Forward PE", font=f(24), fill=C["muted"])
    d.text((410, 1014), f"{safe_num(qqq.get('forward_pe'))}x", font=f(56, True), fill=C["blue"])
    d.line((705, 958, 705, 1038), fill=C["border"], width=2)
    qqq_sig = "偏买"
    if qqq.get("forward_pe") is not None:
        try:
            qv = float(qqq["forward_pe"])
            if qv >= 30:
                qqq_sig = "偏卖"
            elif qv <= 22:
                qqq_sig = "偏买"
            else:
                qqq_sig = "中立"
        except Exception:
            qqq_sig = "中立"

    d.text((760, 970), "估值信号", font=f(24), fill=C["muted"])
    d.text((760, 1014), qqq_sig, font=f(50, True), fill=signal_color(qqq_sig))
    d.ellipse((900, 950, 980, 1030), outline=signal_color(qqq_sig), width=6)
    d.text((940, 990), "✓", font=f(54, True), fill=signal_color(qqq_sig), anchor="mm")

    # Explanation video promo
    neon_box(base, (55, 1170, 1025, 1510), glow_color=C["blue"])
    # play icon
    neon_box(base, (95, 1260, 300, 1445), glow_color=C["blue"], fill=C["panel2"], radius=20)
    d.polygon([(160, 1310), (160, 1395), (245, 1352)], fill=C["blue"])
    d.text((360, 1245), f"为什么今天是{result}？", font=f(54, True), fill=C["text"])
    d.text((360, 1330), "VIX｜VXN｜Put/Call｜Fear & Greed｜", font=f(28), fill=C["text"])
    d.text((360, 1375), "AAII｜黄金/铜｜10Y美债｜QQQ估值", font=f(28), fill=C["text"])
    d.line((360, 1435, 980, 1435), fill=hex_to_rgba(C["blue"], 160), width=2)
    draw_glow_text(base, (360, 1465), "判断逻辑详情请看我的解释视频  »", f(38, True), C["yellow"], C["yellow"])

    # logic chips
    neon_box(base, (55, 1550, 1025, 1790), glow_color=C["blue"])
    d.text((540, 1580), "关键逻辑要点", font=f(34, True), fill=C["blue"], anchor="ma")

    chips = summary_logic_chips(data)
    chip_xs = [95, 335, 575, 815]
    for idx, chip in enumerate(chips[:4]):
        draw_logic_chip(base, chip_xs[idx], 1630, chip["title"], chip["line1"], chip["line2"], chip["color"])

    d.line((150, 1832, 930, 1832), fill=hex_to_rgba(C["blue"], 140), width=2)
    d.text((540, 1855), "🛡 仅供参考，不构成任何投资建议", font=f(25), fill=C["muted"], anchor="ma")

    base.convert("RGB").save(output)


def summary_logic_chips(data: dict[str, Any]) -> list[dict[str, str]]:
    details = data["overall_signal"]["details"]

    selected = []
    priority = [
        "VXN",
        "AAII Bull-Bear Spread",
        "10Y Treasury Yield",
        "纳斯达克100 Forward PE",
        "QQQ Forward PE",
    ]
    for key in priority:
        for item in details:
            if item["indicator"] == key:
                selected.append(item)
                break

    def chip_text(item: dict[str, Any]) -> tuple[str, str]:
        ind = item["indicator"]
        sig = item["signal"]
        if ind == "VXN":
            return "VXN高位", f"→ {sig}"
        if ind == "AAII Bull-Bear Spread":
            return "AAII偏悲观", f"→ {sig}"
        if ind == "10Y Treasury Yield":
            return "10Y美债高位", f"→ {sig}"
        if "Forward PE" in ind:
            return "QQQ Forward PE偏低" if sig == "偏买" else "QQQ估值", f"→ {sig}"
        return ind, f"→ {sig}"

    out = []
    for item in selected[:4]:
        line1, line2 = chip_text(item)
        out.append({
            "title": logic_icon(item["indicator"]),
            "line1": line1,
            "line2": line2,
            "color": signal_color(item["signal"]),
        })

    while len(out) < 4:
        out.append({
            "title": "◎",
            "line1": "市场观察",
            "line2": "→ 中立",
            "color": C["blue"],
        })
    return out


def logic_icon(name: str) -> str:
    if name == "VXN":
        return "📈"
    if name == "AAII Bull-Bear Spread":
        return "👥"
    if name == "10Y Treasury Yield":
        return "🏛"
    if "Forward PE" in name:
        return "📊"
    return "◎"


def draw_logic_chip(base: Image.Image, x: int, y: int, icon_text: str, line1: str, line2: str, color: str):
    d = ImageDraw.Draw(base)
    if x != 95:
        d.line((x - 20, y + 5, x - 20, y + 140), fill=hex_to_rgba(C["border"], 140), width=2)
    d.ellipse((x + 10, y, x + 90, y + 80), outline=color, width=4)
    d.text((x + 50, y + 40), icon_text, font=f(34, True), fill=color, anchor="mm")
    d.text((x, y + 92), line1, font=f(22), fill=C["text"])
    d.text((x, y + 132), line2, font=f(22, True), fill=color)


def meter_arc(base: Image.Image, box: tuple[int, int, int, int], score: int) -> None:
    d = ImageDraw.Draw(base)
    x0, y0, x1, y1 = box
    d.arc(box, start=180, end=360, fill=C["blue2"], width=12)
    d.arc(box, start=300, end=360, fill=C["green"], width=14)

    cx = (x0 + x1) // 2
    cy = y1
    r = (x1 - x0) // 2 - 12

    marks = [(-6, 180), (-4, 210), (-2, 240), (0, 270), (2, 300), (4, 330), (6, 360)]
    for val, ang in marks:
        px = cx + math.cos(math.radians(ang)) * r
        py = cy + math.sin(math.radians(ang)) * r
        px2 = cx + math.cos(math.radians(ang)) * (r - 20)
        py2 = cy + math.sin(math.radians(ang)) * (r - 20)
        d.line((px, py, px2, py2), fill=C["text"], width=3)
        lx = cx + math.cos(math.radians(ang)) * (r + 30)
        ly = cy + math.sin(math.radians(ang)) * (r + 10)
        d.text((lx, ly), f"{val:+d}" if val > 0 else str(val), font=f(16), fill=C["text"], anchor="mm")

    score = max(-6, min(6, int(score)))
    angle = 270 + score * 15
    px = cx + math.cos(math.radians(angle)) * (r - 30)
    py = cy + math.sin(math.radians(angle)) * (r - 30)
    d.line((cx, cy, px, py), fill=C["green"], width=10)
    d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), outline=C["green"], width=4)
    d.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=C["green"])


def count_chip(base: Image.Image, box: tuple[int, int, int, int], text: str, color: str):
    neon_box(base, box, glow_color=color, fill=C["panel"], radius=22, line_color=color, line_width=3)
    draw_glow_text(base, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), text, f(50, True), color, color, anchor="mm")


def build_video(cards: list[Path], output: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        segments: list[Path] = []

        for index, card in enumerate(cards, start=1):
            segment = tmp_dir / f"segment_{index:02d}.mp4"
            vf = (
                f"scale={WIDTH}:{HEIGHT},"
                "zoompan=z='min(zoom+0.00025,1.02)':"
                "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d=113:s={WIDTH}x{HEIGHT}:fps=30,"
                "fade=t=in:st=0:d=0.18,"
                "fade=t=out:st=3.57:d=0.18,"
                "format=yuv420p"
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-framerate",
                    "30",
                    "-i",
                    str(card),
                    "-t",
                    "3.75",
                    "-vf",
                    vf,
                    "-an",
                    "-r",
                    "30",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    str(segment),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            segments.append(segment)

        concat_file = tmp_dir / "segments.txt"
        concat_file.write_text(
            "\n".join(f"file '{segment.as_posix()}'" for segment in segments),
            encoding="utf-8",
        )

        silent_video = tmp_dir / "video_only.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                str(silent_video),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(silent_video),
                "-f",
                "lavfi",
                "-t",
                "15",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-t",
                "15",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/latest_data.json")
    parser.add_argument("--output-dir", default="output/media")
    args = parser.parse_args()

    data = parse_json(args.input)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    cards = [
        out / "01_volatility.png",
        out / "02_sentiment.png",
        out / "03_macro.png",
        out / "04_summary.png",
    ]

    render_volatility(data, cards[0])
    render_sentiment(data, cards[1])
    render_macro(data, cards[2])
    render_summary(data, cards[3])
    build_video(cards, out / "market_risk_short.mp4")

    print(
        json.dumps(
            {
                "cards": [str(x) for x in cards],
                "video": str(out / "market_risk_short.mp4"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
