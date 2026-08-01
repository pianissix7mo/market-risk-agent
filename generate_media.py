from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1920
FPS = 30

COLORS = {
    "background": "#06101C",
    "background_bottom": "#091828",
    "card": "#0E1D2D",
    "card_alt": "#0A1725",
    "card_highlight": "#14283D",
    "border": "#29425D",
    "border_soft": "#1A3047",
    "text": "#F6F9FC",
    "muted": "#AAB7C7",
    "dim": "#74869A",
    "accent": "#58A6FF",
    "accent_soft": "#173D63",
    "green": "#3DDC97",
    "yellow": "#F3C95B",
    "red": "#FF6B72",
}

REGULAR_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]
BOLD_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]


def first_existing(candidates: list[tuple[str, int]]) -> tuple[str, int]:
    for path, index in candidates:
        if Path(path).exists():
            return path, index
    raise RuntimeError("No suitable font found. Install fonts-noto-cjk.")


REGULAR_FONT = first_existing(REGULAR_CANDIDATES)
BOLD_FONT = first_existing(BOLD_CANDIDATES)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path, index = BOLD_FONT if bold else REGULAR_FONT
    return ImageFont.truetype(path, size=size, index=index)


def parse_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def signal_color(signal: str) -> str:
    return {
        "偏买": COLORS["green"],
        "中立": COLORS["yellow"],
        "偏卖": COLORS["red"],
    }.get(signal, COLORS["muted"])


def safe_num(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "--"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "--"


def rank_text(value: Any) -> str:
    if value is None:
        return "P--"
    try:
        return f"P{int(round(float(value)))}"
    except (TypeError, ValueError):
        return "P--"


def text_width(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), text, font=text_font, anchor="lt")
    return box[2] - box[0]


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int,
    min_size: int,
    bold: bool = False,
) -> ImageFont.FreeTypeFont:
    for size in range(start_size, min_size - 1, -2):
        candidate = font(size, bold)
        if text_width(draw, text, candidate) <= max_width:
            return candidate
    return font(min_size, bold)


def draw_fitted_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    max_width: int,
    start_size: int,
    min_size: int,
    fill: str,
    bold: bool = False,
    anchor: str = "lt",
) -> None:
    draw.text(
        xy,
        text,
        font=fit_font(draw, text, max_width, start_size, min_size, bold),
        fill=fill,
        anchor=anchor,
    )


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def blend_rgb(a: str, b: str, t: float) -> tuple[int, int, int]:
    ar, ag, ab = hex_rgb(a)
    br, bg, bb = hex_rgb(b)
    return (
        int(ar + (br - ar) * t),
        int(ag + (bg - ag) * t),
        int(ab + (bb - ab) * t),
    )


def text_with_shadow(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    anchor: str = "lt",
    shadow_offset: tuple[int, int] = (0, 7),
) -> None:
    draw = ImageDraw.Draw(image)
    sx, sy = shadow_offset
    draw.text((xy[0] + sx, xy[1] + sy), text, font=text_font, fill="#02070C", anchor=anchor)
    draw.text(xy, text, font=text_font, fill=fill, anchor=anchor)


def subtle_glow_text(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    anchor: str = "lt",
) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    rgb = hex_rgb(fill)
    ld.text(xy, text, font=text_font, fill=(*rgb, 72), anchor=anchor)
    layer = layer.filter(ImageFilter.GaussianBlur(14))
    image.alpha_composite(layer)
    ImageDraw.Draw(image).text(xy, text, font=text_font, fill=fill, anchor=anchor)


def canvas() -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image)

    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        draw.line((0, y, WIDTH, y), fill=blend_rgb(COLORS["background"], COLORS["background_bottom"], t))

    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-260, -180, 540, 620), fill=(42, 117, 196, 42))
    gd.ellipse((680, 1150, 1320, 2040), fill=(25, 91, 151, 28))
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    image.alpha_composite(glow)

    draw.rectangle((0, 0, 10, HEIGHT), fill="#1B4B78")
    draw.rectangle((10, 0, 14, HEIGHT), fill="#0A2239")
    draw.line((40, 34, 174, 34), fill="#21486A", width=2)
    draw.line((40, 34, 40, 96), fill="#21486A", width=2)
    draw.line((906, 1880, 1040, 1880), fill="#173A5A", width=2)
    draw.line((1040, 1818, 1040, 1880), fill="#173A5A", width=2)
    return image


def rounded_card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    signal: str | None = None,
    fill: str | None = None,
) -> None:
    x0, y0, x1, y1 = box
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x0 + 8, y0 + 14, x1 + 8, y1 + 14), radius=34, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    image.alpha_composite(shadow)

    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        box,
        radius=34,
        fill=fill or COLORS["card"],
        outline=COLORS["border"],
        width=2,
    )
    draw.rounded_rectangle(
        (x0 + 2, y0 + 2, x1 - 2, y1 - 2),
        radius=32,
        outline=COLORS["border_soft"],
        width=1,
    )
    draw.line((x0 + 30, y0 + 26, x1 - 30, y0 + 26), fill="#17334D", width=2)
    draw.polygon([(x1 - 98, y0), (x1, y0), (x1, y0 + 98)], fill="#102B43")
    if signal:
        color = signal_color(signal)
        draw.rounded_rectangle((x0, y0 + 34, x0 + 10, y1 - 34), radius=5, fill=color)
        draw.line((x0 + 30, y0 + 26, x0 + 190, y0 + 26), fill=color, width=3)


def draw_header(image: Image.Image, market_date: str, category: str, page_index: str) -> None:
    draw = ImageDraw.Draw(image)
    draw.text((72, 62), "MARKET RISK MONITOR", font=font(22, True), fill=COLORS["accent"], anchor="lt")
    draw.text((72, 100), "每日美股风险温度", font=font(49, True), fill=COLORS["text"], anchor="lt")
    draw.text((72, 171), market_date, font=font(25), fill=COLORS["muted"], anchor="lt")

    draw.rounded_rectangle((650, 66, 930, 130), radius=20, fill="#0E2438", outline=COLORS["border"], width=2)
    draw.text((676, 98), page_index, font=font(22, True), fill=COLORS["accent"], anchor="lm")
    draw.text((908, 98), category, font=font(23, True), fill=COLORS["text"], anchor="rm")

    draw.line((72, 221, 930, 221), fill=COLORS["border"], width=2)
    draw.line((72, 221, 235, 221), fill=COLORS["accent"], width=4)


def draw_footer(image: Image.Image, source: str) -> None:
    draw = ImageDraw.Draw(image)
    draw.line((72, 1682, 930, 1682), fill=COLORS["border"], width=2)
    draw_fitted_text(
        draw,
        (72, 1717),
        f"数据来源：{source}",
        858,
        24,
        20,
        COLORS["dim"],
    )
    draw.text(
        (72, 1804),
        "仅供参考，不构成任何投资建议",
        font=font(27),
        fill=COLORS["muted"],
        anchor="lt",
    )


def draw_signal(draw: ImageDraw.ImageDraw, signal: str, x: int, y: int) -> None:
    color = signal_color(signal)
    draw.rounded_rectangle((x, y, x + 182, y + 76), radius=24, fill="#091521", outline=color, width=3)
    draw.rounded_rectangle((x + 10, y + 10, x + 20, y + 66), radius=5, fill=color)
    draw.text((x + 106, y + 38), signal, font=font(39, True), fill=color, anchor="mm")


def vol_signal(label: str, percentile: Any) -> tuple[str, str]:
    if percentile is None:
        return "中立", f"{label}缺少过去3年分位数据"
    value = float(percentile)
    if value >= 75:
        return "偏买", "波动压力较高，反向信号偏买"
    if value <= 25:
        return "偏卖", "市场波动较低，反向信号偏卖"
    return "中立", "处于过去3年中性区间"


def draw_percentile_track(
    image: Image.Image,
    x: int,
    y: int,
    width: int,
    percentile: Any,
    color: str,
) -> None:
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((x, y, x + width, y + 12), radius=6, fill="#07121E")
    try:
        p = max(0.0, min(100.0, float(percentile)))
    except (TypeError, ValueError):
        p = 0.0
    px = x + int(width * p / 100.0)
    draw.rounded_rectangle((x, y, max(x + 10, px), y + 12), radius=6, fill=color)
    draw.ellipse((px - 9, y - 3, px + 9, y + 15), fill=COLORS["text"], outline=color, width=4)
    draw.text((x, y + 28), "0", font=font(18), fill=COLORS["dim"], anchor="lt")
    draw.text((x + width // 2, y + 28), "50", font=font(18), fill=COLORS["dim"], anchor="mt")
    draw.text((x + width, y + 28), "100", font=font(18), fill=COLORS["dim"], anchor="rt")


def draw_large_metric_card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    title: str,
    subtitle: str,
    value: str,
    signal: str,
    percentile: Any,
    explanation: str,
    value_size: int = 154,
) -> None:
    rounded_card(image, box, signal)
    draw = ImageDraw.Draw(image)
    x0, y0, x1, _ = box
    left = x0 + 42
    right = x1 - 38
    color = signal_color(signal)

    draw.text((left, y0 + 48), "RISK INDICATOR", font=font(19, True), fill=color, anchor="lt")
    draw_fitted_text(draw, (left, y0 + 82), title, 560, 46, 34, COLORS["text"], True)
    draw_fitted_text(draw, (left, y0 + 146), subtitle, 610, 27, 22, COLORS["muted"])

    number_font = fit_font(draw, value, 600, value_size, 108, True)
    text_with_shadow(image, (left, y0 + 205), value, number_font, COLORS["text"])
    draw_signal(draw, signal, right - 182, y0 + 225)

    draw.text((left, y0 + 372), f"3年分位  {rank_text(percentile)}", font=font(32, True), fill=COLORS["accent"], anchor="lt")
    draw_percentile_track(image, left, y0 + 425, 520, percentile, color)
    draw_fitted_text(draw, (left, y0 + 480), explanation, 780, 27, 22, COLORS["muted"])


def render_volatility(data: dict[str, Any], output: Path) -> None:
    image = canvas()
    draw_header(image, data["market_date"], "波动率", "01 / 04")

    vix = data["volatility"]["vix"]
    vxn = data["volatility"]["vxn"]
    vix_signal, vix_explanation = vol_signal("VIX", vix.get("percentile_3y"))
    vxn_signal, vxn_explanation = vol_signal("VXN", vxn.get("percentile_3y"))

    draw_large_metric_card(
        image,
        (72, 270, 930, 795),
        "VIX",
        "标普500波动率",
        safe_num(vix.get("value"), 2),
        vix_signal,
        vix.get("percentile_3y"),
        vix_explanation,
    )
    draw_large_metric_card(
        image,
        (72, 835, 930, 1360),
        "VXN",
        "纳斯达克100波动率",
        safe_num(vxn.get("value"), 2),
        vxn_signal,
        vxn.get("percentile_3y"),
        vxn_explanation,
    )
    draw_footer(image, "Yahoo Finance")
    image.convert("RGB").save(output, quality=95)


def draw_sentiment_card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    title: str,
    value: str,
    signal: str,
    explanation: str,
    descriptor: str | None = None,
    secondary: str | None = None,
) -> None:
    rounded_card(image, box, signal)
    draw = ImageDraw.Draw(image)
    x0, y0, x1, _ = box
    left = x0 + 42
    right = x1 - 38
    color = signal_color(signal)

    draw.text((left, y0 + 38), "SENTIMENT", font=font(18, True), fill=color, anchor="lt")
    draw_fitted_text(draw, (left, y0 + 70), title, 590, 40, 30, COLORS["text"], True)
    value_font = fit_font(draw, value, 520, 118, 86, True)
    text_with_shadow(image, (left, y0 + 132), value, value_font, COLORS["text"])
    draw_signal(draw, signal, right - 182, y0 + 142)

    if descriptor:
        draw.rounded_rectangle((left + 395, y0 + 170, left + 525, y0 + 220), radius=16, fill="#0A1A28", outline=COLORS["border"], width=2)
        draw_fitted_text(draw, (left + 460, y0 + 195), descriptor, 110, 27, 21, COLORS["muted"], True, anchor="mm")
    if secondary:
        draw_fitted_text(draw, (left, y0 + 300), secondary, 770, 30, 23, COLORS["accent"], True)
        explanation_y = y0 + 365
    else:
        explanation_y = y0 + 292
    draw.line((left, explanation_y - 22, right, explanation_y - 22), fill=COLORS["border_soft"], width=2)
    draw_fitted_text(draw, (left, explanation_y), explanation, 770, 27, 22, COLORS["muted"])


def render_sentiment(data: dict[str, Any], output: Path) -> None:
    image = canvas()
    draw_header(image, data["market_date"], "市场情绪", "02 / 04")

    macro = data["macro"]
    pc = macro["equity_put_call"]
    fg = macro["fear_greed"]
    aaii = macro["aaii_sentiment"]

    draw_sentiment_card(
        image,
        (72, 260, 930, 630),
        "Equity Put/Call",
        safe_num(pc.get("value"), 2),
        pc.get("signal", "中立"),
        "市场保护情绪处于中性区间" if pc.get("signal") == "中立" else pc.get("explanation", ""),
    )
    draw_sentiment_card(
        image,
        (72, 670, 930, 1040),
        "CNN Fear & Greed",
        safe_num(fg.get("value"), 2),
        fg.get("signal", "中立"),
        "尚未进入极度恐惧或极度贪婪" if fg.get("signal") == "中立" else fg.get("explanation", ""),
        descriptor=str(fg.get("rating", "")).replace("fear", "恐惧").replace("greed", "贪婪"),
    )
    draw_sentiment_card(
        image,
        (72, 1080, 930, 1585),
        "AAII Bull-Bear Spread",
        safe_num(aaii.get("bull_bear_spread"), 1),
        aaii.get("signal", "中立"),
        "悲观情绪明显较高，反向信号偏买" if aaii.get("signal") == "偏买" else aaii.get("explanation", ""),
        secondary=(
            f"Bearish {safe_num(aaii.get('bearish'), 1, '%')}  >  "
            f"Bullish {safe_num(aaii.get('bullish'), 1, '%')}"
        ),
    )
    draw_footer(image, "Cboe / CNN / AAII")
    image.convert("RGB").save(output, quality=95)


def render_macro(data: dict[str, Any], output: Path) -> None:
    image = canvas()
    draw_header(image, data["market_date"], "宏观压力", "03 / 04")

    gc = data["macro"]["gold_copper_ratio"]
    ty = data["macro"]["treasury_10y"]

    draw_large_metric_card(
        image,
        (72, 280, 930, 810),
        "Gold / Copper Ratio",
        "黄金/铜比",
        safe_num(gc.get("value"), 2),
        gc.get("signal", "中立"),
        gc.get("percentile_3y"),
        "判断主要使用历史分位",
        value_size=140,
    )
    draw_large_metric_card(
        image,
        (72, 850, 930, 1380),
        "10Y Treasury Yield",
        "10年美债收益率",
        safe_num(ty.get("value"), 3, "%"),
        ty.get("signal", "中立"),
        ty.get("percentile_3y"),
        "收益率处于高位，对估值形成压力" if ty.get("signal") == "偏卖" else ty.get("explanation", ""),
        value_size=140,
    )
    draw_footer(image, "Yahoo Finance")
    image.convert("RGB").save(output, quality=95)


def qqq_signal(forward_pe: Any) -> str:
    if forward_pe is None:
        return "中立"
    value = float(forward_pe)
    if value <= 22:
        return "偏买"
    if value >= 30:
        return "偏卖"
    return "中立"


def render_summary(data: dict[str, Any], output: Path) -> None:
    image = canvas()
    draw_header(image, data["market_date"], "估值与判断", "04 / 04")
    draw = ImageDraw.Draw(image)

    overall = data["overall_signal"]
    result = overall.get("result", "中立")
    result_color = signal_color(result)
    qqq = data["valuation"]["nasdaq100"]
    valuation_signal = qqq_signal(qqq.get("forward_pe"))

    draw_fitted_text(draw, (72, 268), f"为什么今天是{result}？", 858, 58, 44, COLORS["text"], True)

    rounded_card(image, (72, 370, 930, 785), result)
    draw = ImageDraw.Draw(image)
    draw.text((114, 414), "TODAY'S SIGNAL", font=font(20, True), fill=result_color, anchor="lt")
    draw.text((114, 455), "综合判断", font=font(31), fill=COLORS["muted"], anchor="lt")
    result_font = fit_font(draw, result, 500, 184, 148, True)
    subtle_glow_text(image, (114, 515), result, result_font, result_color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((114, 704, 316, 714), fill=result_color)
    draw.text((344, 708), "市场风险与估值信号综合", font=font(25), fill=COLORS["muted"], anchor="lm")

    score = int(overall.get("score", 0))
    draw.rounded_rectangle((724, 440, 876, 598), radius=76, fill="#091622", outline=result_color, width=4)
    draw.text((800, 485), "SCORE", font=font(18, True), fill=COLORS["muted"], anchor="mm")
    draw.text((800, 548), f"{score:+d}", font=font(62, True), fill=result_color, anchor="mm")

    rounded_card(image, (72, 835, 930, 1245), valuation_signal)
    draw = ImageDraw.Draw(image)
    draw.text((114, 878), "QQQ VALUATION", font=font(20, True), fill=COLORS["accent"], anchor="lt")
    draw.text((114, 920), "QQQ 估值", font=font(34, True), fill=COLORS["text"], anchor="lt")

    draw.rounded_rectangle((106, 992, 480, 1185), radius=26, fill="#091827", outline=COLORS["border_soft"], width=2)
    draw.rounded_rectangle((522, 992, 896, 1185), radius=26, fill="#091827", outline=COLORS["border_soft"], width=2)
    draw.text((138, 1023), "QQQ PE", font=font(27), fill=COLORS["muted"], anchor="lt")
    text_with_shadow(image, (138, 1068), safe_num(qqq.get("trailing_pe"), 2, "x"), font(72, True), COLORS["text"])
    draw = ImageDraw.Draw(image)
    draw.text((138, 1150), "当前估值", font=font(23), fill=COLORS["dim"], anchor="lt")

    draw.text((554, 1023), "QQQ Forward PE", font=font(27), fill=COLORS["muted"], anchor="lt")
    text_with_shadow(image, (554, 1068), safe_num(qqq.get("forward_pe"), 2, "x"), font(72, True), COLORS["text"])
    draw = ImageDraw.Draw(image)
    draw.text((554, 1150), valuation_signal, font=font(26, True), fill=signal_color(valuation_signal), anchor="lt")

    rounded_card(image, (72, 1300, 930, 1588), fill=COLORS["card_alt"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((106, 1345, 118, 1538), fill=result_color)
    draw_fitted_text(draw, (148, 1350), f"为什么今天是{result}？", 720, 48, 38, COLORS["text"], True)
    draw_fitted_text(draw, (148, 1444), "判断逻辑详情请看我的解释视频", 720, 40, 31, COLORS["accent"], True)
    draw.text((148, 1515), "VIX · 情绪 · 宏观 · QQQ估值", font=font(23), fill=COLORS["dim"], anchor="lt")

    draw_footer(image, "Yahoo Finance / Cboe / CNN / AAII / ETF PE History")
    image.convert("RGB").save(output, quality=95)


def build_video(cards: list[Path], output: Path) -> None:
    hold_frames = 111
    transition_frames = 2
    total_frames = hold_frames * 4 + transition_frames * 3
    assert total_frames == FPS * 15

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        sequence_images: list[tuple[Path, int]] = []

        for index, card in enumerate(cards):
            sequence_images.append((card, hold_frames))
            if index < len(cards) - 1:
                with Image.open(card).convert("RGB") as first, Image.open(cards[index + 1]).convert("RGB") as second:
                    transition = Image.blend(first, second, 0.5)
                    transition_path = temp_dir / f"transition_{index + 1}.png"
                    transition.save(transition_path)
                sequence_images.append((transition_path, transition_frames))

        segments: list[Path] = []
        for index, (still, frame_count) in enumerate(sequence_images):
            segment = temp_dir / f"segment_{index:02d}.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-framerate", str(FPS),
                    "-i", str(still),
                    "-frames:v", str(frame_count),
                    "-an",
                    "-r", str(FPS),
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    "-g", str(FPS),
                    "-keyint_min", str(FPS),
                    "-sc_threshold", "0",
                    str(segment),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            segments.append(segment)

        concat_file = temp_dir / "segments.txt"
        concat_file.write_text(
            "\n".join(f"file '{segment.as_posix()}'" for segment in segments),
            encoding="utf-8",
        )

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-frames:v", str(total_frames),
                "-an",
                "-r", str(FPS),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
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
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cards = [
        output_dir / "01_volatility.png",
        output_dir / "02_sentiment.png",
        output_dir / "03_macro.png",
        output_dir / "04_summary.png",
    ]

    render_volatility(data, cards[0])
    render_sentiment(data, cards[1])
    render_macro(data, cards[2])
    render_summary(data, cards[3])
    build_video(cards, output_dir / "market_risk_short.mp4")

    print(
        json.dumps(
            {
                "cards": [str(path) for path in cards],
                "video": str(output_dir / "market_risk_short.mp4"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
