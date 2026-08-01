from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1920
FPS = 30

COLORS = {
    "background": "#07111F",
    "card": "#101D2E",
    "card_alt": "#0D1928",
    "border": "#26384E",
    "text": "#F4F7FB",
    "muted": "#A9B4C3",
    "dim": "#738297",
    "accent": "#65A9FF",
    "green": "#39D98A",
    "yellow": "#F2C94C",
    "red": "#FF6B6B",
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


def canvas() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image)
    # Restrained financial-tech accent; no grid, glow or decorative chart.
    draw.rectangle((0, 0, 14, HEIGHT), fill="#18365B")
    draw.rectangle((14, 0, 18, HEIGHT), fill="#0C2038")
    return image


def rounded_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    signal: str | None = None,
    fill: str | None = None,
) -> None:
    draw.rounded_rectangle(
        box,
        radius=32,
        fill=fill or COLORS["card"],
        outline=COLORS["border"],
        width=2,
    )
    if signal:
        x0, y0, x1, _ = box
        draw.rounded_rectangle(
            (x0, y0, x1, y0 + 12),
            radius=6,
            fill=signal_color(signal),
        )


def draw_header(image: Image.Image, market_date: str, category: str) -> None:
    draw = ImageDraw.Draw(image)
    draw.text((72, 70), "每日美股风险温度", font=font(48, True), fill=COLORS["text"], anchor="lt")
    draw.text((72, 142), market_date, font=font(27), fill=COLORS["muted"], anchor="lt")
    draw.text((930, 142), category, font=font(27), fill=COLORS["muted"], anchor="rt")
    draw.line((72, 205, 930, 205), fill=COLORS["border"], width=2)


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
    draw.rounded_rectangle((x, y, x + 182, y + 76), radius=22, outline=color, width=3)
    draw.text((x + 91, y + 38), signal, font=font(40, True), fill=color, anchor="mm")


def vol_signal(label: str, percentile: Any) -> tuple[str, str]:
    if percentile is None:
        return "中立", f"{label}缺少过去3年分位数据"
    value = float(percentile)
    if value >= 75:
        return "偏买", "波动压力较高，反向信号偏买"
    if value <= 25:
        return "偏卖", "市场波动较低，反向信号偏卖"
    return "中立", "处于过去3年中性区间"


def draw_large_metric_card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    title: str,
    subtitle: str,
    value: str,
    signal: str,
    secondary: str,
    explanation: str,
    value_size: int = 154,
) -> None:
    draw = ImageDraw.Draw(image)
    rounded_card(draw, box, signal)
    x0, y0, x1, _ = box
    left = x0 + 34
    right = x1 - 34

    draw_fitted_text(draw, (left, y0 + 48), title, 520, 44, 34, COLORS["text"], True)
    draw_fitted_text(draw, (left, y0 + 112), subtitle, 600, 28, 22, COLORS["muted"])
    draw_fitted_text(draw, (left, y0 + 184), value, 610, value_size, 112, COLORS["text"], True)
    draw_signal(draw, signal, right - 182, y0 + 203)
    draw.text((left, y0 + 385), secondary, font=font(34, True), fill=COLORS["accent"], anchor="lt")
    draw_fitted_text(draw, (left, y0 + 447), explanation, 790, 28, 23, COLORS["muted"])


def render_volatility(data: dict[str, Any], output: Path) -> None:
    image = canvas()
    draw_header(image, data["market_date"], "波动率")

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
        f"3年分位  {rank_text(vix.get('percentile_3y'))}",
        vix_explanation,
    )
    draw_large_metric_card(
        image,
        (72, 835, 930, 1360),
        "VXN",
        "纳斯达克100波动率",
        safe_num(vxn.get("value"), 2),
        vxn_signal,
        f"3年分位  {rank_text(vxn.get('percentile_3y'))}",
        vxn_explanation,
    )
    draw_footer(image, "Yahoo Finance")
    image.save(output, quality=95)


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
    draw = ImageDraw.Draw(image)
    rounded_card(draw, box, signal)
    x0, y0, x1, _ = box
    left = x0 + 34
    right = x1 - 34

    draw_fitted_text(draw, (left, y0 + 43), title, 570, 38, 29, COLORS["text"], True)
    draw_fitted_text(draw, (left, y0 + 108), value, 570, 120, 88, COLORS["text"], True)
    draw_signal(draw, signal, right - 182, y0 + 127)
    if descriptor:
        draw_fitted_text(draw, (left + 400, y0 + 162), descriptor, 260, 30, 23, COLORS["muted"], True)
    if secondary:
        draw_fitted_text(draw, (left, y0 + 280), secondary, 790, 31, 24, COLORS["accent"])
        explanation_y = y0 + 342
    else:
        explanation_y = y0 + 280
    draw_fitted_text(draw, (left, explanation_y), explanation, 790, 28, 22, COLORS["muted"])


def render_sentiment(data: dict[str, Any], output: Path) -> None:
    image = canvas()
    draw_header(image, data["market_date"], "市场情绪")

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
    image.save(output, quality=95)


def render_macro(data: dict[str, Any], output: Path) -> None:
    image = canvas()
    draw_header(image, data["market_date"], "宏观压力")

    gc = data["macro"]["gold_copper_ratio"]
    ty = data["macro"]["treasury_10y"]

    draw_large_metric_card(
        image,
        (72, 280, 930, 810),
        "Gold / Copper Ratio",
        "黄金/铜比",
        safe_num(gc.get("value"), 2),
        gc.get("signal", "中立"),
        f"3年分位  {rank_text(gc.get('percentile_3y'))}",
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
        f"3年分位  {rank_text(ty.get('percentile_3y'))}",
        "收益率处于高位，对估值形成压力" if ty.get("signal") == "偏卖" else ty.get("explanation", ""),
        value_size=140,
    )
    draw_footer(image, "Yahoo Finance")
    image.save(output, quality=95)


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
    draw_header(image, data["market_date"], "估值与判断")
    draw = ImageDraw.Draw(image)

    overall = data["overall_signal"]
    result = overall.get("result", "中立")
    result_color = signal_color(result)
    qqq = data["valuation"]["nasdaq100"]
    valuation_signal = qqq_signal(qqq.get("forward_pe"))

    draw_fitted_text(
        draw,
        (72, 270),
        f"为什么今天是{result}？",
        858,
        58,
        44,
        COLORS["text"],
        True,
    )

    rounded_card(draw, (72, 370, 930, 780), result)
    draw.text((106, 420), "综合判断", font=font(31), fill=COLORS["muted"], anchor="lt")
    draw_fitted_text(draw, (106, 485), result, 610, 180, 142, result_color, True)
    draw.rectangle((106, 690, 286, 700), fill=result_color)

    rounded_card(draw, (72, 835, 930, 1235), valuation_signal)
    draw.text((106, 885), "QQQ 估值", font=font(35, True), fill=COLORS["text"], anchor="lt")
    draw.line((501, 950, 501, 1164), fill=COLORS["border"], width=2)

    draw.text((106, 966), "QQQ PE", font=font(30), fill=COLORS["muted"], anchor="lt")
    draw_fitted_text(
        draw,
        (106, 1020),
        safe_num(qqq.get("trailing_pe"), 2, "x"),
        340,
        92,
        68,
        COLORS["text"],
        True,
    )
    draw.text((106, 1137), "当前估值", font=font(25), fill=COLORS["dim"], anchor="lt")

    draw.text((548, 966), "QQQ Forward PE", font=font(30), fill=COLORS["muted"], anchor="lt")
    draw_fitted_text(
        draw,
        (548, 1020),
        safe_num(qqq.get("forward_pe"), 2, "x"),
        335,
        92,
        68,
        COLORS["text"],
        True,
    )
    draw.text((548, 1137), valuation_signal, font=font(30, True), fill=signal_color(valuation_signal), anchor="lt")

    rounded_card(draw, (72, 1290, 930, 1580), fill=COLORS["card_alt"])
    draw_fitted_text(
        draw,
        (106, 1350),
        f"为什么今天是{result}？",
        790,
        48,
        38,
        COLORS["text"],
        True,
    )
    draw_fitted_text(
        draw,
        (106, 1442),
        "判断逻辑详情请看我的解释视频",
        790,
        42,
        32,
        COLORS["accent"],
        True,
    )

    draw_footer(image, "Yahoo Finance / Cboe / CNN / AAII / ETF PE History")
    image.save(output, quality=95)


def build_video(cards: list[Path], output: Path) -> None:
    # Use four static holds and three two-frame Pillow blends. This avoids
    # black flashes, zooming and FFmpeg xfade compatibility differences.
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
