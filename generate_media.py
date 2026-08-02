from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT, FPS = 1080, 1920, 30
CX = WIDTH // 2
LEFT, RIGHT = 96, 954

C = {
    "bg": "#06101C",
    "bg2": "#091828",
    "card": "#0C1B2B",
    "card_alt": "#091723",
    "border": "#29425D",
    "border2": "#1A3047",
    "text": "#F6F9FC",
    "muted": "#AAB7C7",
    "dim": "#74869A",
    "blue": "#58A6FF",
    "green": "#3DDC97",
    "yellow": "#F3C95B",
    "red": "#FF6B72",
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


def blend(a: str, b: str, t: float) -> tuple[int, int, int]:
    aa, bb = rgb(a), rgb(b)
    return tuple(int(x + (y - x) * t) for x, y in zip(aa, bb))


def fit(draw: ImageDraw.ImageDraw, text: str, width: int, start: int, minimum: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for size in range(start, minimum - 1, -2):
        f = font(size, bold)
        box = draw.textbbox((0, 0), text, font=f, anchor="lt")
        if box[2] - box[0] <= width:
            return f
    return font(minimum, bold)


def fitted(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, width: int, start: int, minimum: int, fill: str, bold: bool = False, anchor: str = "lt") -> None:
    draw.text(xy, text, font=fit(draw, text, width, start, minimum, bold), fill=fill, anchor=anchor)


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
    return {"偏买": C["green"], "中立": C["yellow"], "偏卖": C["red"]}.get(signal, C["muted"])


def text_shadow(image: Image.Image, xy: tuple[int, int], text: str, f: ImageFont.FreeTypeFont, fill: str, anchor: str = "mm") -> None:
    draw = ImageDraw.Draw(image)
    draw.text((xy[0], xy[1] + 7), text, font=f, fill="#02070C", anchor=anchor)
    draw.text(xy, text, font=f, fill=fill, anchor=anchor)


def glow_text(image: Image.Image, xy: tuple[int, int], text: str, f: ImageFont.FreeTypeFont, fill: str) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text(xy, text, font=f, fill=(*rgb(fill), 72), anchor="mm")
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(14)))
    ImageDraw.Draw(image).text(xy, text, font=f, fill=fill, anchor="mm")


def background() -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), C["bg"])
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = blend(C["bg"], "#08203A", t / 0.55) if t < 0.55 else blend("#08203A", C["bg2"], (t - 0.55) / 0.45)
        draw.line((0, y, WIDTH, y), fill=color)

    light = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(light)
    ld.ellipse((-220, -120, 620, 700), fill=(40, 132, 224, 58))
    ld.ellipse((640, 980, 1300, 1940), fill=(21, 98, 184, 44))
    ld.ellipse((220, 1180, 920, 2060), fill=(7, 72, 145, 30))
    image.alpha_composite(light.filter(ImageFilter.GaussianBlur(120)))

    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 90):
        draw.line((x, 0, x, HEIGHT), fill=(32, 73, 112, 28))
    for y in range(0, HEIGHT, 100):
        draw.line((0, y, WIDTH, y), fill=(32, 73, 112, 24))

    chart = Image.new("RGBA", image.size, (0, 0, 0, 0))
    cd = ImageDraw.Draw(chart)
    for start, stop, step, base, opacity in [(560, 1040, 32, 420, 65), (60, 520, 34, 1470, 50)]:
        points: list[tuple[int, int]] = []
        for i, x in enumerate(range(start, stop, step)):
            wave = math.sin(i * (0.55 if start > 500 else 0.52))
            y = base + int((40 if start > 500 else 36) * wave) - i * (2 if start > 500 else 4)
            points.append((x, y))
            color = (76, 209, 159, opacity) if i % 4 != 2 else (255, 107, 114, opacity)
            cd.line((x, y - 38, x, y + 30), fill=color, width=2)
            cd.rectangle((x - 7, y - 16, x + 7, y + 16), fill=color)
        cd.line(points, fill=(80, 175, 255, opacity + 10), width=4)
    image.alpha_composite(chart.filter(ImageFilter.GaussianBlur(1)))

    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 10, HEIGHT), fill="#1B4B78")
    draw.rectangle((10, 0, 14, HEIGHT), fill="#0A2239")
    draw.line((40, 34, 174, 34), fill="#2E6594", width=2)
    draw.line((40, 34, 40, 96), fill="#2E6594", width=2)
    draw.line((906, 1880, 1040, 1880), fill="#2E6594", width=2)
    draw.line((1040, 1818, 1040, 1880), fill="#2E6594", width=2)
    return image


def card(image: Image.Image, box: tuple[int, int, int, int], signal: str | None = None, fill: str | None = None) -> None:
    x0, y0, x1, y1 = box
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x0 + 8, y0 + 14, x1 + 8, y1 + 14), radius=34, fill=(0, 0, 0, 150))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(20)))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(box, radius=34, fill=fill or C["card"], outline=C["border"], width=2)
    draw.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y1 - 2), radius=32, outline=C["border2"], width=1)
    draw.line((x0 + 30, y0 + 26, x1 - 30, y0 + 26), fill="#17334D", width=2)
    draw.polygon([(x1 - 98, y0), (x1, y0), (x1, y0 + 98)], fill="#102B43")
    if signal:
        color = signal_color(signal)
        draw.rounded_rectangle((x0, y0 + 34, x0 + 10, y1 - 34), radius=5, fill=color)
        draw.line((x0 + 30, y0 + 26, x0 + 190, y0 + 26), fill=color, width=3)


def header(image: Image.Image, market_date: str, category: str) -> None:
    draw = ImageDraw.Draw(image)
    draw.text((CX, 58), "MARKET RISK MONITOR", font=font(22, True), fill=C["blue"], anchor="ma")
    draw.text((CX, 96), "每日美股风险温度", font=font(52, True), fill=C["text"], anchor="ma")

    draw.rounded_rectangle((380, 176, 700, 242), radius=20, fill="#10263B", outline=C["border"], width=2)
    draw.text((CX, 209), market_date, font=font(38, True), fill=C["text"], anchor="mm")

    draw.rounded_rectangle((430, 258, 650, 322), radius=20, fill="#0E2438", outline=C["border"], width=2)
    draw.text((CX, 290), category, font=font(24, True), fill=C["text"], anchor="mm")
    draw.line((164, 350, 964, 350), fill=C["border"], width=2)
    draw.line((409, 350, 719, 350), fill=C["blue"], width=4)


def footer(image: Image.Image, source: str) -> None:
    draw = ImageDraw.Draw(image)
    draw.line((LEFT, 1700, RIGHT, 1700), fill=C["border"], width=2)
    fitted(draw, (LEFT, 1732), f"数据来源：{source}", RIGHT - LEFT, 24, 19, C["dim"])
    draw.text((LEFT, 1818), "仅供参考，不构成任何投资建议", font=font(27), fill=C["muted"], anchor="lt")


def signal_pill(draw: ImageDraw.ImageDraw, signal: str, center_x: int, y: int) -> None:
    color = signal_color(signal)
    x = center_x - 82
    draw.rounded_rectangle((x, y, x + 164, y + 64), radius=20, fill="#091521", outline=color, width=3)
    draw.rounded_rectangle((x + 10, y + 10, x + 18, y + 54), radius=4, fill=color)
    draw.text((x + 95, y + 32), signal, font=font(33, True), fill=color, anchor="mm")


def percentile_bar(image: Image.Image, center_x: int, y: int, percentile: Any, color: str) -> None:
    draw = ImageDraw.Draw(image)
    x, width = center_x - 260, 520
    draw.rounded_rectangle((x, y, x + width, y + 12), radius=6, fill="#07121E")
    try:
        p = max(0.0, min(100.0, float(percentile)))
    except (TypeError, ValueError):
        p = 0.0
    px = x + int(width * p / 100)
    draw.rounded_rectangle((x, y, max(x + 10, px), y + 12), radius=6, fill=color)
    draw.ellipse((px - 9, y - 3, px + 9, y + 15), fill=C["text"], outline=color, width=4)


def volatility_signal(percentile: Any) -> tuple[str, str]:
    try:
        p = float(percentile)
    except (TypeError, ValueError):
        return "中立", "缺少过去3年分位数据"
    if p >= 75:
        return "偏买", "波动压力较高，反向信号偏买"
    if p <= 25:
        return "偏卖", "市场波动较低，反向信号偏卖"
    return "中立", "处于过去3年中性区间"


def metric_card(image: Image.Image, box: tuple[int, int, int, int], title: str, subtitle: str, value: str, signal: str, percentile: Any, explanation: str, value_size: int = 132) -> None:
    card(image, box, signal)
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    color = signal_color(signal)
    draw.text((cx, y0 + 46), "RISK INDICATOR", font=font(19, True), fill=color, anchor="mm")
    fitted(draw, (cx, y0 + 88), title, 650, 46, 34, C["text"], True, "mm")
    fitted(draw, (cx, y0 + 132), subtitle, 650, 27, 22, C["muted"], anchor="mm")
    value_font = fit(draw, value, 560, value_size, 92, True)
    text_shadow(image, (cx, y0 + 238), value, value_font, C["text"])
    signal_pill(draw, signal, cx, y0 + 320)
    draw.text((cx, y0 + 414), f"3年分位  {rank(percentile)}", font=font(30, True), fill=C["blue"], anchor="mm")
    percentile_bar(image, cx, y0 + 444, percentile, color)
    fitted(draw, (cx, y0 + 492), explanation, 760, 27, 22, C["muted"], anchor="mm")
    assert y0 + 512 <= y1


def sentiment_card(image: Image.Image, box: tuple[int, int, int, int], title: str, value: str, signal: str, explanation: str, descriptor: str | None = None, secondary: str | None = None) -> None:
    card(image, box, signal)
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    color = signal_color(signal)
    draw.text((cx, y0 + 40), "SENTIMENT", font=font(18, True), fill=color, anchor="mm")
    fitted(draw, (cx, y0 + 82), title, 650, 40, 30, C["text"], True, "mm")

    if descriptor:
        draw.rounded_rectangle((cx - 66, y0 + 112, cx + 66, y0 + 158), radius=15, fill="#0A1A28", outline=C["border"], width=2)
        fitted(draw, (cx, y0 + 135), descriptor, 110, 25, 20, C["muted"], True, "mm")
        number_y, pill_y, explanation_y = y0 + 212, y0 + 262, y0 + 338
    else:
        number_y, pill_y, explanation_y = y0 + 168, y0 + 220, y0 + 304

    text_shadow(image, (cx, number_y), value, fit(draw, value, 430, 86, 66, True), C["text"])
    signal_pill(draw, signal, cx, pill_y)
    if secondary:
        fitted(draw, (cx, y0 + 344), secondary, 760, 29, 22, C["blue"], True, "mm")
        explanation_y = y0 + 410
    fitted(draw, (cx, explanation_y), explanation, 760, 26, 21, C["muted"], anchor="mm")
    assert explanation_y + 32 <= y1


def render_volatility(data: dict[str, Any], output: Path) -> None:
    image = background()
    header(image, data["market_date"], "波动率")
    vix, vxn = data["volatility"]["vix"], data["volatility"]["vxn"]
    vix_signal, vix_note = volatility_signal(vix.get("percentile_3y"))
    vxn_signal, vxn_note = volatility_signal(vxn.get("percentile_3y"))
    metric_card(image, (LEFT, 390, RIGHT, 912), "VIX", "标普500波动率", number(vix.get("value")), vix_signal, vix.get("percentile_3y"), vix_note)
    metric_card(image, (LEFT, 956, RIGHT, 1478), "VXN", "纳斯达克100波动率", number(vxn.get("value")), vxn_signal, vxn.get("percentile_3y"), vxn_note)
    footer(image, "Yahoo Finance")
    image.convert("RGB").save(output, quality=95)


def render_sentiment(data: dict[str, Any], output: Path) -> None:
    image = background()
    header(image, data["market_date"], "市场情绪")
    macro = data["macro"]
    pc, fg, aaii = macro["equity_put_call"], macro["fear_greed"], macro["aaii_sentiment"]
    sentiment_card(image, (LEFT, 390, RIGHT, 735), "Equity Put/Call", number(pc.get("value")), pc.get("signal", "中立"), "市场保护情绪处于中性区间" if pc.get("signal") == "中立" else pc.get("explanation", ""))
    sentiment_card(image, (LEFT, 770, RIGHT, 1155), "CNN Fear & Greed", number(fg.get("value")), fg.get("signal", "中立"), "尚未进入极度恐惧或极度贪婪" if fg.get("signal") == "中立" else fg.get("explanation", ""), descriptor=str(fg.get("rating", "")).replace("fear", "恐惧").replace("greed", "贪婪"))
    sentiment_card(image, (LEFT, 1190, RIGHT, 1650), "AAII Bull-Bear Spread", number(aaii.get("bull_bear_spread"), 1), aaii.get("signal", "中立"), "悲观情绪明显较高，反向信号偏买" if aaii.get("signal") == "偏买" else aaii.get("explanation", ""), secondary=f"Bearish {number(aaii.get('bearish'), 1, '%')}  >  Bullish {number(aaii.get('bullish'), 1, '%')}")
    footer(image, "Cboe / CNN / AAII")
    image.convert("RGB").save(output, quality=95)


def render_macro(data: dict[str, Any], output: Path) -> None:
    image = background()
    header(image, data["market_date"], "宏观压力")
    gc, ty = data["macro"]["gold_copper_ratio"], data["macro"]["treasury_10y"]
    metric_card(image, (LEFT, 390, RIGHT, 912), "Gold / Copper Ratio", "黄金/铜比", number(gc.get("value")), gc.get("signal", "中立"), gc.get("percentile_3y"), "判断主要使用历史分位", 120)
    metric_card(image, (LEFT, 956, RIGHT, 1478), "10Y Treasury Yield", "10年美债收益率", number(ty.get("value"), 3, "%"), ty.get("signal", "中立"), ty.get("percentile_3y"), "收益率处于高位，对估值形成压力" if ty.get("signal") == "偏卖" else ty.get("explanation", ""), 120)
    footer(image, "Yahoo Finance")
    image.convert("RGB").save(output, quality=95)


def qqq_signal(value: Any) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "中立"
    return "偏买" if value <= 22 else "偏卖" if value >= 30 else "中立"


def render_summary(data: dict[str, Any], output: Path) -> None:
    image = background()
    header(image, data["market_date"], "估值与判断")
    draw = ImageDraw.Draw(image)
    overall = data["overall_signal"]
    result = overall.get("result", "中立")
    result_color = signal_color(result)
    qqq = data["valuation"]["nasdaq100"]
    value_signal = qqq_signal(qqq.get("forward_pe"))

    fitted(draw, (CX, 412), f"为什么今天是{result}？", 760, 52, 40, C["text"], True, "mm")
    card(image, (LEFT, 460, RIGHT, 895), result)
    draw = ImageDraw.Draw(image)
    draw.text((CX, 508), "TODAY'S SIGNAL", font=font(20, True), fill=result_color, anchor="mm")
    draw.text((CX, 552), "综合判断", font=font(31), fill=C["muted"], anchor="mm")
    glow_text(image, (CX, 680), result, fit(draw, result, 460, 160, 128, True), result_color)
    draw = ImageDraw.Draw(image)
    draw.text((CX, 830), f"综合分数 {int(overall.get('score', 0)):+d}", font=font(27, True), fill=C["muted"], anchor="mm")

    card(image, (LEFT, 935, RIGHT, 1335), value_signal)
    draw = ImageDraw.Draw(image)
    draw.text((CX, 980), "QQQ VALUATION", font=font(20, True), fill=C["blue"], anchor="mm")
    draw.text((CX, 1022), "QQQ 估值", font=font(35, True), fill=C["text"], anchor="mm")
    left_box, right_box = (136, 1080, 516, 1278), (534, 1080, 914, 1278)
    draw.rounded_rectangle(left_box, radius=26, fill="#071523", outline=C["border2"], width=2)
    draw.rounded_rectangle(right_box, radius=26, fill="#071523", outline=C["border2"], width=2)
    lcx, rcx = 326, 724
    draw.text((lcx, 1114), "QQQ PE", font=font(27), fill=C["muted"], anchor="mm")
    text_shadow(image, (lcx, 1180), number(qqq.get("trailing_pe"), 2, "x"), font(64, True), C["text"])
    draw = ImageDraw.Draw(image)
    draw.text((lcx, 1252), "当前估值", font=font(23), fill=C["dim"], anchor="mm")
    draw.text((rcx, 1114), "QQQ Forward PE", font=font(25), fill=C["muted"], anchor="mm")
    text_shadow(image, (rcx, 1180), number(qqq.get("forward_pe"), 2, "x"), font(64, True), C["text"])
    draw = ImageDraw.Draw(image)
    draw.text((rcx, 1252), value_signal, font=font(25, True), fill=signal_color(value_signal), anchor="mm")

    card(image, (LEFT, 1375, RIGHT, 1655), fill=C["card_alt"])
    draw = ImageDraw.Draw(image)
    fitted(draw, (CX, 1450), f"为什么今天是{result}？", 720, 48, 38, C["text"], True, "mm")
    fitted(draw, (CX, 1532), "判断逻辑详情请看我的解释视频", 760, 40, 31, C["blue"], True, "mm")
    draw.text((CX, 1596), "VIX · 情绪 · 宏观 · QQQ估值", font=font(23), fill=C["dim"], anchor="mm")
    footer(image, "Yahoo Finance / Cboe / CNN / AAII / ETF PE History")
    image.convert("RGB").save(output, quality=95)


def build_video(cards: list[Path], output: Path) -> None:
    hold, transition = 111, 2
    total = hold * 4 + transition * 3
    assert total == FPS * 15
    with tempfile.TemporaryDirectory() as temp_name:
        temp = Path(temp_name)
        sequence: list[tuple[Path, int]] = []
        for i, card_path in enumerate(cards):
            sequence.append((card_path, hold))
            if i < len(cards) - 1:
                with Image.open(card_path).convert("RGB") as first, Image.open(cards[i + 1]).convert("RGB") as second:
                    transition_path = temp / f"transition_{i}.png"
                    Image.blend(first, second, 0.5).save(transition_path)
                sequence.append((transition_path, transition))

        segments: list[Path] = []
        for i, (still, frames) in enumerate(sequence):
            segment = temp / f"segment_{i:02d}.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(still),
                "-frames:v", str(frames), "-an", "-r", str(FPS), "-c:v", "libx264",
                "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-g", str(FPS),
                "-keyint_min", str(FPS), "-sc_threshold", "0", str(segment),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segments.append(segment)

        concat = temp / "segments.txt"
        concat.write_text("\n".join(f"file '{segment.as_posix()}'" for segment in segments), encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-frames:v", str(total), "-an", "-r", str(FPS), "-c:v", "libx264",
            "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/latest_data.json")
    parser.add_argument("--output-dir", default="output/media")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cards = [output_dir / "01_volatility.png", output_dir / "02_sentiment.png", output_dir / "03_macro.png", output_dir / "04_summary.png"]
    render_volatility(data, cards[0])
    render_sentiment(data, cards[1])
    render_macro(data, cards[2])
    render_summary(data, cards[3])
    video = output_dir / "market_risk_short.mp4"
    build_video(cards, video)
    print(json.dumps({"cards": [str(path) for path in cards], "video": str(video)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
