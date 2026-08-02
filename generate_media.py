from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1080, 1920
CX = WIDTH // 2
LEFT, RIGHT = 92, 988

C = {
    "bg": "#07131F",
    "bg2": "#0C2136",
    "card": "#0F2032",
    "card_alt": "#10263C",
    "line": "#274564",
    "text": "#F4F8FC",
    "muted": "#A9B9CA",
    "dim": "#7E90A5",
    "blue": "#63B3FF",
    "green": "#37D39A",
    "yellow": "#F5C85C",
    "red": "#FF6B72",
    "white": "#FFFFFF",
}

FONT_REGULAR = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]
FONT_BOLD = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]


def pick_font(candidates: list[tuple[str, int]]) -> tuple[str, int]:
    for path, index in candidates:
        if Path(path).exists():
            return path, index
    raise RuntimeError("Install fonts-noto-cjk before generating media.")


REGULAR = pick_font(FONT_REGULAR)
BOLD = pick_font(FONT_BOLD)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path, index = BOLD if bold else REGULAR
    return ImageFont.truetype(path, size=size, index=index)


def rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def number(value: Any, digits: int = 2, suffix: str = "") -> str:
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "--"


def rank(value: Any) -> str:
    try:
        return f"P{int(round(float(value)))}"
    except (TypeError, ValueError):
        return "P--"


def signal_color(signal: str) -> str:
    return {
        "偏买": C["green"],
        "中立": C["yellow"],
        "偏卖": C["red"],
    }.get(signal, C["muted"])


def text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    text_font: ImageFont.FreeTypeFont,
) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=text_font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    text_font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Pixel-based wrapping that works for mixed Chinese and English text."""
    if not text:
        return [""]

    lines: list[str] = []
    current = ""

    for character in text:
        if character == "\n":
            lines.append(current)
            current = ""
            continue

        candidate = current + character
        if not current or text_size(draw, candidate, text_font)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = character

    if current or not lines:
        lines.append(current)
    return lines


def fit_text_in_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    start_size: int,
    min_size: int,
    *,
    bold: bool = False,
    line_gap: int = 8,
    max_lines: int | None = None,
) -> tuple[ImageFont.FreeTypeFont, list[str], int, int]:
    """Wrap and shrink text until both width and height fit the target box."""
    x0, y0, x1, y1 = box
    max_width = x1 - x0
    max_height = y1 - y0

    for size in range(start_size, min_size - 1, -2):
        text_font = font(size, bold)
        lines = wrap_text_to_width(draw, text, text_font, max_width)

        if max_lines is not None and len(lines) > max_lines:
            continue

        line_height = text_size(draw, "中Ag", text_font)[1]
        total_height = len(lines) * line_height + max(0, len(lines) - 1) * line_gap

        widest = max((text_size(draw, line, text_font)[0] for line in lines), default=0)
        if widest <= max_width and total_height <= max_height:
            return text_font, lines, line_height, total_height

    raise ValueError(
        f"Text does not fit box {box} even at minimum size {min_size}: {text!r}"
    )


def draw_text_in_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    *,
    fill: str = C["text"],
    start_size: int = 32,
    min_size: int = 18,
    bold: bool = False,
    align: str = "left",
    valign: str = "top",
    line_gap: int = 8,
    max_lines: int | None = None,
) -> tuple[int, int, int, int]:
    """Draw text inside a fixed box and return its actual bounding box."""
    x0, y0, x1, y1 = box
    text_font, lines, line_height, total_height = fit_text_in_box(
        draw,
        text,
        box,
        start_size,
        min_size,
        bold=bold,
        line_gap=line_gap,
        max_lines=max_lines,
    )

    if valign == "top":
        y = y0
    elif valign == "middle":
        y = y0 + ((y1 - y0) - total_height) // 2
    elif valign == "bottom":
        y = y1 - total_height
    else:
        raise ValueError(f"Unsupported valign: {valign}")

    actual_left = x1
    actual_top = y
    actual_right = x0
    actual_bottom = y

    for line in lines:
        line_width, _ = text_size(draw, line, text_font)

        if align == "left":
            x = x0
        elif align == "center":
            x = x0 + ((x1 - x0) - line_width) // 2
        elif align == "right":
            x = x1 - line_width
        else:
            raise ValueError(f"Unsupported align: {align}")

        draw.text((x, y), line, font=text_font, fill=fill)
        actual_left = min(actual_left, x)
        actual_right = max(actual_right, x + line_width)
        actual_bottom = y + line_height
        y += line_height + line_gap

    actual = (actual_left, actual_top, actual_right, actual_bottom)
    assert_box_inside(actual, box, f"text: {text}")
    return actual


def assert_box_inside(
    inner: tuple[int, int, int, int],
    outer: tuple[int, int, int, int],
    label: str,
) -> None:
    if not (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    ):
        raise AssertionError(f"{label} left its box: inner={inner}, outer={outer}")


def background() -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), C["bg"])
    draw = ImageDraw.Draw(image)

    start = rgb(C["bg"])
    end = rgb(C["bg2"])
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = tuple(int(start[i] * (1 - t) + end[i] * t) for i in range(3))
        draw.line((0, y, WIDTH, y), fill=color)

    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((-200, -100, 500, 600), fill=(70, 140, 220, 50))
    glow_draw.ellipse((650, 1100, 1250, 1800), fill=(30, 90, 180, 45))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))

    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 90):
        draw.line((x, 0, x, HEIGHT), fill=(40, 80, 120, 25))
    for y in range(0, HEIGHT, 100):
        draw.line((0, y, WIDTH, y), fill=(40, 80, 120, 20))

    return image


def rounded_card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    fill: str = C["card"],
    outline: str = C["line"],
    width: int = 2,
    radius: int = 28,
    shadow: bool = True,
) -> None:
    if shadow:
        shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        x0, y0, x1, y1 = box
        shadow_draw.rounded_rectangle(
            (x0 + 6, y0 + 10, x1 + 6, y1 + 10),
            radius=radius,
            fill=(0, 0, 0, 110),
        )
        image.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(18)))

    ImageDraw.Draw(image).rounded_rectangle(
        box,
        radius=radius,
        fill=fill,
        outline=outline,
        width=width,
    )


def header(image: Image.Image, market_date: str, category: str) -> None:
    draw = ImageDraw.Draw(image)
    draw.text(
        (CX, 60),
        "MARKET RISK MONITOR",
        font=font(22, True),
        fill=C["blue"],
        anchor="ma",
    )
    draw.text(
        (CX, 100),
        "每日美股风险温度",
        font=font(52, True),
        fill=C["text"],
        anchor="ma",
    )

    rounded_card(
        image,
        (370, 176, 710, 244),
        fill="#10263B",
        radius=18,
        shadow=False,
    )
    draw.text(
        (CX, 210),
        market_date,
        font=font(38, True),
        fill=C["text"],
        anchor="mm",
    )

    rounded_card(
        image,
        (430, 258, 650, 318),
        fill="#0E2236",
        radius=18,
        shadow=False,
    )
    draw_text_in_box(
        draw,
        (445, 272, 635, 306),
        category,
        start_size=24,
        min_size=20,
        bold=True,
        align="center",
        valign="middle",
        max_lines=1,
    )

    draw.line((150, 350, 930, 350), fill=C["line"], width=2)
    draw.line((420, 350, 660, 350), fill=C["blue"], width=4)


def footer(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    draw.line((LEFT, 1770, RIGHT, 1770), fill=C["line"], width=2)
    draw.text(
        (LEFT, 1810),
        "仅供参考，不构成投资建议",
        font=font(26),
        fill=C["muted"],
    )


def signal_pill(
    image: Image.Image,
    box: tuple[int, int, int, int],
    signal: str,
) -> None:
    color = signal_color(signal)
    rounded_card(
        image,
        box,
        fill="#091521",
        outline=color,
        width=3,
        radius=18,
        shadow=False,
    )
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(
        (x0 + 10, y0 + 10, x0 + 18, y1 - 10),
        radius=4,
        fill=color,
    )
    draw_text_in_box(
        draw,
        (x0 + 28, y0 + 8, x1 - 8, y1 - 8),
        signal,
        fill=color,
        start_size=28,
        min_size=24,
        bold=True,
        align="center",
        valign="middle",
        max_lines=1,
    )


def percentile_bar(
    image: Image.Image,
    box: tuple[int, int, int, int],
    percentile: Any,
    color: str,
) -> None:
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=6, fill="#08121C")

    try:
        value = max(0.0, min(100.0, float(percentile)))
    except (TypeError, ValueError):
        value = 0.0

    progress_x = x0 + int((x1 - x0) * value / 100)
    draw.rounded_rectangle(
        (x0, y0, max(x0 + 10, progress_x), y1),
        radius=6,
        fill=color,
    )
    center_y = (y0 + y1) // 2
    draw.ellipse(
        (progress_x - 9, center_y - 9, progress_x + 9, center_y + 9),
        fill=C["white"],
        outline=color,
        width=3,
    )


def volatility_signal(percentile: Any) -> tuple[str, str]:
    try:
        value = float(percentile)
    except (TypeError, ValueError):
        return "中立", "缺少过去3年分位数据"

    if value >= 75:
        return "偏买", "波动处于高位，反向信号偏买。"
    if value <= 25:
        return "偏卖", "波动处于低位，反向信号偏卖。"
    return "中立", "处于过去3年中性区间。"


def indicator_card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    title: str,
    subtitle: str,
    value: str,
    signal: str,
    percentile: Any,
    note: str,
) -> None:
    rounded_card(image, box)
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    color = signal_color(signal)

    draw_text_in_box(
        draw,
        (x0 + 36, y0 + 28, x1 - 36, y0 + 54),
        "RISK INDICATOR",
        fill=color,
        start_size=18,
        min_size=16,
        bold=True,
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (x0 + 36, y0 + 64, x1 - 36, y0 + 116),
        title,
        start_size=44,
        min_size=34,
        bold=True,
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (x0 + 36, y0 + 118, x1 - 36, y0 + 152),
        subtitle,
        fill=C["muted"],
        start_size=24,
        min_size=20,
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (x0 + 36, y0 + 170, x1 - 36, y0 + 288),
        value,
        start_size=112,
        min_size=72,
        bold=True,
        align="center",
        valign="middle",
        max_lines=1,
    )

    signal_pill(image, (x0 + 36, y0 + 286, x0 + 180, y0 + 342), signal)

    draw_text_in_box(
        draw,
        (x0 + 36, y0 + 368, x1 - 36, y0 + 404),
        f"3年分位  {rank(percentile)}",
        fill=C["blue"],
        start_size=28,
        min_size=24,
        bold=True,
        max_lines=1,
    )
    percentile_bar(
        image,
        (x0 + 36, y0 + 414, x1 - 36, y0 + 426),
        percentile,
        color,
    )
    draw_text_in_box(
        draw,
        (x0 + 36, y0 + 446, x1 - 36, y1 - 30),
        note,
        fill=C["muted"],
        start_size=24,
        min_size=19,
        line_gap=6,
        max_lines=2,
    )


def sentiment_card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    title: str,
    value: str,
    signal: str,
    note: str,
    extra: str | None = None,
) -> None:
    rounded_card(image, box)
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box

    draw_text_in_box(
        draw,
        (x0 + 32, y0 + 28, x1 - 210, y0 + 70),
        title,
        start_size=34,
        min_size=26,
        bold=True,
        max_lines=1,
    )
    signal_pill(image, (x1 - 180, y0 + 24, x1 - 32, y0 + 80), signal)

    draw_text_in_box(
        draw,
        (x0 + 32, y0 + 96, x1 - 32, y0 + 170),
        value,
        start_size=72,
        min_size=56,
        bold=True,
        max_lines=1,
    )

    note_top = y0 + 192
    if extra:
        draw_text_in_box(
            draw,
            (x0 + 32, y0 + 174, x1 - 32, y0 + 214),
            extra,
            fill=C["blue"],
            start_size=26,
            min_size=21,
            max_lines=1,
        )
        note_top = y0 + 228

    draw_text_in_box(
        draw,
        (x0 + 32, note_top, x1 - 32, y1 - 28),
        note,
        fill=C["muted"],
        start_size=24,
        min_size=19,
        line_gap=6,
        max_lines=3,
    )


def qqq_signal(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "中立"
    return "偏买" if numeric <= 22 else "偏卖" if numeric >= 30 else "中立"


def render_volatility(data: dict[str, Any], output: Path) -> None:
    image = background()
    header(image, str(data["market_date"]), "波动率")

    vix = data["volatility"]["vix"]
    vxn = data["volatility"]["vxn"]

    vix_signal, vix_note = volatility_signal(vix.get("percentile_3y"))
    vxn_signal, vxn_note = volatility_signal(vxn.get("percentile_3y"))

    indicator_card(
        image,
        (LEFT, 398, RIGHT, 912),
        title="VIX",
        subtitle="标普500波动率",
        value=number(vix.get("value")),
        signal=vix_signal,
        percentile=vix.get("percentile_3y"),
        note=vix_note,
    )
    indicator_card(
        image,
        (LEFT, 958, RIGHT, 1472),
        title="VXN",
        subtitle="纳斯达克100波动率",
        value=number(vxn.get("value")),
        signal=vxn_signal,
        percentile=vxn.get("percentile_3y"),
        note=vxn_note,
    )

    footer(image)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, quality=95)


def render_sentiment(data: dict[str, Any], output: Path) -> None:
    image = background()
    header(image, str(data["market_date"]), "市场情绪")

    macro = data["macro"]
    put_call = macro["equity_put_call"]
    fear_greed = macro["fear_greed"]
    aaii = macro["aaii_sentiment"]

    sentiment_card(
        image,
        (LEFT, 392, RIGHT, 732),
        title="Equity Put/Call",
        value=number(put_call.get("value")),
        signal=put_call.get("signal", "中立"),
        note=put_call.get("explanation", "Put/Call处于中性区间。"),
    )

    rating = str(fear_greed.get("rating", "")).strip()
    sentiment_card(
        image,
        (LEFT, 770, RIGHT, 1110),
        title="CNN Fear & Greed",
        value=number(fear_greed.get("value")),
        signal=fear_greed.get("signal", "中立"),
        extra=f"评级：{rating.title()}" if rating else None,
        note=fear_greed.get("explanation", "恐惧贪婪指数处于中性区间。"),
    )

    sentiment_card(
        image,
        (LEFT, 1148, RIGHT, 1608),
        title="AAII Bull-Bear Spread",
        value=number(aaii.get("bull_bear_spread"), 1),
        signal=aaii.get("signal", "中立"),
        extra=(
            f"Bearish {number(aaii.get('bearish'), 1, '%')}  >  "
            f"Bullish {number(aaii.get('bullish'), 1, '%')}"
        ),
        note=aaii.get(
            "explanation",
            "悲观情绪明显高于乐观情绪，反向信号偏买。",
        ),
    )

    footer(image)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, quality=95)


def render_macro(data: dict[str, Any], output: Path) -> None:
    image = background()
    header(image, str(data["market_date"]), "宏观压力")

    gold_copper = data["macro"]["gold_copper_ratio"]
    treasury = data["macro"]["treasury_10y"]

    indicator_card(
        image,
        (LEFT, 398, RIGHT, 912),
        title="Gold / Copper Ratio",
        subtitle="黄金 / 铜比",
        value=number(gold_copper.get("value")),
        signal=gold_copper.get("signal", "中立"),
        percentile=gold_copper.get("percentile_3y"),
        note=gold_copper.get(
            "explanation",
            "位于过去3年中性区间，暂无明显宏观压力信号。",
        ),
    )
    indicator_card(
        image,
        (LEFT, 958, RIGHT, 1472),
        title="10Y Treasury Yield",
        subtitle="10年美债收益率",
        value=number(treasury.get("value"), 3, "%"),
        signal=treasury.get("signal", "中立"),
        percentile=treasury.get("percentile_3y"),
        note=treasury.get(
            "explanation",
            "收益率位于高位，对科技股估值偏不利。",
        ),
    )

    footer(image)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, quality=95)


def render_summary(data: dict[str, Any], output: Path) -> None:
    image = background()
    header(image, str(data["market_date"]), "估值与判断")
    draw = ImageDraw.Draw(image)

    overall = data["overall_signal"]
    result = overall.get("result", "中立")
    score = int(overall.get("score", 0))
    result_color = signal_color(result)

    qqq = data["valuation"]["nasdaq100"]
    trailing_pe = number(qqq.get("trailing_pe"), 2, "x")
    forward_pe = number(qqq.get("forward_pe"), 2, "x")
    valuation_signal = qqq_signal(qqq.get("forward_pe"))

    details = overall.get("details", [])
    buy_reasons = [
        str(item.get("reason", "")).strip()
        for item in details
        if item.get("signal") == "偏买" and item.get("reason")
    ]
    sell_reasons = [
        str(item.get("reason", "")).strip()
        for item in details
        if item.get("signal") == "偏卖" and item.get("reason")
    ]

    reason_parts = buy_reasons[:2]
    if sell_reasons:
        reason_parts.append(f"但{sell_reasons[0]}")
    summary_reason = "；".join(reason_parts) or "综合指标暂时没有形成明显方向。"

    signal_box = (LEFT, 392, RIGHT, 900)
    rounded_card(image, signal_box)

    draw_text_in_box(
        draw,
        (LEFT + 36, 426, RIGHT - 36, 458),
        "TODAY'S SIGNAL",
        fill=result_color,
        start_size=20,
        min_size=18,
        bold=True,
        align="center",
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (LEFT + 36, 470, RIGHT - 36, 514),
        "综合判断",
        fill=C["muted"],
        start_size=30,
        min_size=26,
        align="center",
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (LEFT + 36, 530, RIGHT - 36, 668),
        result,
        fill=result_color,
        start_size=150,
        min_size=110,
        bold=True,
        align="center",
        valign="middle",
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (LEFT + 36, 680, RIGHT - 36, 720),
        f"综合分数 {score:+d}",
        fill=C["muted"],
        start_size=28,
        min_size=24,
        bold=True,
        align="center",
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (LEFT + 42, 748, RIGHT - 42, 862),
        summary_reason,
        fill=C["muted"],
        start_size=25,
        min_size=19,
        align="center",
        line_gap=6,
        max_lines=3,
    )

    valuation_box = (LEFT, 950, RIGHT, 1328)
    rounded_card(image, valuation_box)
    draw_text_in_box(
        draw,
        (LEFT + 36, 978, RIGHT - 36, 1024),
        "QQQ 估值",
        start_size=34,
        min_size=28,
        bold=True,
        align="center",
        max_lines=1,
    )

    left_box = (132, 1060, 500, 1260)
    right_box = (580, 1060, 948, 1260)
    for box in (left_box, right_box):
        rounded_card(image, box, fill="#081623", shadow=False)

    draw_text_in_box(
        draw,
        (150, 1084, 482, 1126),
        "QQQ PE",
        fill=C["muted"],
        start_size=28,
        min_size=24,
        align="center",
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (150, 1140, 482, 1212),
        trailing_pe,
        start_size=66,
        min_size=52,
        bold=True,
        align="center",
        valign="middle",
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (150, 1220, 482, 1252),
        "当前估值",
        fill=C["dim"],
        start_size=24,
        min_size=20,
        align="center",
        max_lines=1,
    )

    draw_text_in_box(
        draw,
        (598, 1084, 930, 1126),
        "QQQ Forward PE",
        fill=C["muted"],
        start_size=26,
        min_size=21,
        align="center",
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (598, 1140, 930, 1212),
        forward_pe,
        start_size=66,
        min_size=52,
        bold=True,
        align="center",
        valign="middle",
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (598, 1220, 930, 1252),
        valuation_signal,
        fill=signal_color(valuation_signal),
        start_size=24,
        min_size=20,
        bold=True,
        align="center",
        max_lines=1,
    )

    reason_box = (LEFT, 1368, RIGHT, 1648)
    rounded_card(image, reason_box, fill=C["card_alt"])
    draw_text_in_box(
        draw,
        (LEFT + 36, 1406, RIGHT - 36, 1460),
        f"为什么今天是{result}？",
        start_size=42,
        min_size=32,
        bold=True,
        align="center",
        max_lines=1,
    )
    draw_text_in_box(
        draw,
        (LEFT + 48, 1490, RIGHT - 48, 1586),
        summary_reason,
        fill=C["blue"],
        start_size=30,
        min_size=22,
        align="center",
        line_gap=6,
        max_lines=3,
    )
    draw_text_in_box(
        draw,
        (LEFT + 36, 1600, RIGHT - 36, 1632),
        "VIX · 情绪 · 宏观 · QQQ估值",
        fill=C["dim"],
        start_size=22,
        min_size=18,
        align="center",
        max_lines=1,
    )

    footer(image)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, quality=95)
