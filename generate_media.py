from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1920

C = {
    "bg": "#07111F",
    "panel": "#102033",
    "panel2": "#172B42",
    "border": "#29435F",
    "text": "#F4F7FB",
    "muted": "#A8BACD",
    "dim": "#73879E",
    "blue": "#66ADFF",
    "green": "#35C98F",
    "yellow": "#F3B84B",
    "red": "#F06B73",
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


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = 28,
    fill: str | None = None,
    outline: str | None = None,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=fill or C["panel"],
        outline=outline or C["border"],
        width=width,
    )


def signal_color(signal: str) -> str:
    return {"偏买": C["green"], "中立": C["yellow"], "偏卖": C["red"]}.get(
        signal, C["muted"]
    )


def pill(
    draw: ImageDraw.ImageDraw, x: int, y: int, signal: str, width: int = 150
) -> None:
    color = signal_color(signal)
    bg = {"偏买": "#15372C", "中立": "#3B311B", "偏卖": "#3B2027"}.get(
        signal, C["panel2"]
    )
    rounded(draw, (x, y, x + width, y + 58), radius=18, fill=bg, outline=color)
    draw.text(
        (x + width // 2, y + 29),
        signal,
        font=f(22, True),
        fill=color,
        anchor="mm",
    )


def wrap(draw: ImageDraw.ImageDraw, text: str, font_obj: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in str(text):
        trial = current + char
        bbox = draw.textbbox((0, 0), trial, font=font_obj)
        if not current or bbox[2] - bbox[0] <= width:
            current = trial
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    *,
    font_obj: ImageFont.FreeTypeFont,
    fill: str,
    width: int,
    spacing: int = 8,
    max_lines: int | None = None,
) -> int:
    lines = wrap(draw, text, font_obj, width)
    if max_lines is not None:
        lines = lines[:max_lines]
    for line in lines:
        draw.text((x, y), line, font=font_obj, fill=fill)
        y += font_obj.size + spacing
    return y


def header(draw: ImageDraw.ImageDraw, title: str, subtitle: str, date_text: str) -> None:
    draw.text((70, 72), title, font=f(58, True), fill=C["text"])
    draw.text((70, 151), subtitle, font=f(25), fill=C["muted"])
    rounded(draw, (775, 72, 1010, 148), radius=20, fill=C["panel2"])
    draw.text(
        (892, 110), date_text, font=f(23, True), fill=C["blue"], anchor="mm"
    )


def footer(draw: ImageDraw.ImageDraw, source: str) -> None:
    draw.line((70, 1790, 1010, 1790), fill=C["border"], width=2)
    draw.text((70, 1820), source, font=f(18), fill=C["dim"])
    draw.text(
        (1010, 1820),
        "仅供参考，不构成任何投资建议",
        font=f(18),
        fill=C["dim"],
        anchor="ra",
    )


def percentile_bar(
    draw: ImageDraw.ImageDraw, x: int, y: int, width: int, percentile: float | None
) -> None:
    draw.rounded_rectangle((x, y, x + width, y + 26), radius=13, fill=C["panel2"])
    for start, end, color in (
        (0.0, 0.25, C["green"]),
        (0.25, 0.75, C["yellow"]),
        (0.75, 1.0, C["red"]),
    ):
        draw.rounded_rectangle(
            (x + int(width * start), y, x + int(width * end), y + 26),
            radius=13,
            fill=color,
        )
    if percentile is not None:
        pos = x + int(width * max(0.0, min(100.0, float(percentile))) / 100)
        draw.line((pos, y - 12, pos, y + 38), fill=C["text"], width=5)
        draw.ellipse((pos - 8, y - 20, pos + 8, y - 4), fill=C["text"])


def detail_signal(data: dict[str, Any], indicator: str) -> str:
    for item in data["overall_signal"]["details"]:
        if item["indicator"] == indicator:
            return str(item["signal"])
    return "中立"


def metric_block(
    draw: ImageDraw.ImageDraw,
    y: int,
    *,
    name: str,
    value: str,
    subtitle: str,
    p1: float | None,
    p3: float | None,
    p5: float | None,
    signal: str,
) -> None:
    rounded(draw, (70, y, 1010, y + 560), radius=34)
    draw.text((110, y + 52), name, font=f(48, True), fill=C["text"])
    draw.text((110, y + 122), subtitle, font=f(23), fill=C["muted"])
    draw.text((950, y + 44), value, font=f(70, True), fill=C["blue"], anchor="ra")
    pill(draw, 800, y + 137, signal)

    for index, (label, val) in enumerate(
        (("过去1年", p1), ("过去3年", p3), ("过去5年", p5))
    ):
        x = 110 + index * 285
        rounded(draw, (x, y + 240, x + 250, y + 350), radius=20, fill=C["panel2"])
        draw.text((x + 22, y + 264), label, font=f(20), fill=C["muted"])
        text = "—" if val is None else f"P{float(val):.0f}"
        draw.text((x + 225, y + 256), text, font=f(38, True), fill=C["text"], anchor="ra")

    draw.text((110, y + 415), "过去3年位置", font=f(22), fill=C["muted"])
    percentile_bar(draw, 110, y + 472, 800, p3)


def render_volatility(data: dict[str, Any], path: Path) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), C["bg"])
    draw = ImageDraw.Draw(img)
    header(draw, "美股波动温度", "VIX 与 VXN 的历史位置", data["market_date"])
    vix = data["volatility"]["vix"]
    vxn = data["volatility"]["vxn"]
    metric_block(
        draw,
        250,
        name="VIX",
        value=f"{vix['value']:.2f}",
        subtitle="标普500 · 30天隐含波动率",
        p1=vix.get("percentile_1y"),
        p3=vix.get("percentile_3y"),
        p5=vix.get("percentile_5y"),
        signal=detail_signal(data, "VIX"),
    )
    metric_block(
        draw,
        890,
        name="VXN",
        value=f"{vxn['value']:.2f}",
        subtitle="纳斯达克100 · 30天隐含波动率",
        p1=vxn.get("percentile_1y"),
        p3=vxn.get("percentile_3y"),
        p5=vxn.get("percentile_5y"),
        signal=detail_signal(data, "VXN"),
    )
    footer(draw, "数据来源：Yahoo Finance")
    img.save(path, optimize=True)


def standard_card(
    draw: ImageDraw.ImageDraw,
    y: int,
    *,
    title: str,
    value: str,
    signal: str,
    explanation: str,
    date_text: str,
    height: int = 390,
) -> None:
    rounded(draw, (70, y, 1010, y + height), radius=30)
    draw.text((110, y + 48), title, font=f(39, True), fill=C["text"])
    draw.text((950, y + 40), value, font=f(54, True), fill=C["blue"], anchor="ra")
    pill(draw, 110, y + 135, signal)
    draw_wrapped(
        draw,
        explanation,
        110,
        y + 225,
        font_obj=f(24),
        fill=C["muted"],
        width=800,
        max_lines=2,
    )
    draw.text((950, y + height - 54), date_text, font=f(19), fill=C["dim"], anchor="ra")


def render_sentiment(data: dict[str, Any], path: Path) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), C["bg"])
    draw = ImageDraw.Draw(img)
    header(draw, "市场情绪", "期权、恐惧贪婪与 AAII 调查", data["market_date"])
    macro = data["macro"]
    pc = macro["equity_put_call"]
    fg = macro["fear_greed"]
    aa = macro["aaii_sentiment"]

    standard_card(
        draw,
        250,
        title="Equity Put/Call",
        value=f"{pc['value']:.2f}",
        signal=pc["signal"],
        explanation=pc["explanation"],
        date_text=pc["date"],
    )
    standard_card(
        draw,
        700,
        title="Fear & Greed",
        value=f"{fg['value']:.2f}",
        signal=fg["signal"],
        explanation=f"{fg['explanation']} · 当前评级 {fg.get('rating', '')}",
        date_text=fg["date"],
    )

    rounded(draw, (70, 1150, 1010, 1695), radius=30)
    draw.text((110, 1200), "AAII Sentiment Survey", font=f(38, True), fill=C["text"])
    pill(draw, 800, 1195, aa["signal"])
    values = (
        ("看多", aa["bullish"], C["green"]),
        ("中立", aa["neutral"], C["yellow"]),
        ("看空", aa["bearish"], C["red"]),
    )
    for index, (label, value, color) in enumerate(values):
        x = 110 + index * 285
        rounded(draw, (x, 1310, x + 250, 1450), radius=22, fill=C["panel2"])
        draw.text((x + 125, 1342), label, font=f(23, True), fill=color, anchor="ma")
        draw.text((x + 125, 1397), f"{value:.1f}%", font=f(38, True), fill=C["text"], anchor="ma")
    draw.text((110, 1515), "Bull-Bear Spread", font=f(23), fill=C["muted"])
    draw.text((950, 1497), f"{aa['bull_bear_spread']:+.1f}", font=f(48, True), fill=signal_color(aa["signal"]), anchor="ra")
    draw_wrapped(
        draw,
        aa["explanation"],
        110,
        1588,
        font_obj=f(23),
        fill=C["muted"],
        width=760,
        max_lines=2,
    )
    draw.text((950, 1640), f"周度 · {aa['date']}", font=f(19), fill=C["dim"], anchor="ra")
    footer(draw, "数据来源：Cboe · CNN · AAII")
    img.save(path, optimize=True)


def render_macro(data: dict[str, Any], path: Path) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), C["bg"])
    draw = ImageDraw.Draw(img)
    header(draw, "宏观风险", "黄金/铜与10年美债收益率", data["market_date"])
    macro = data["macro"]
    gc = macro["gold_copper_ratio"]
    ty = macro["treasury_10y"]

    metric_block(
        draw,
        250,
        name="黄金 / 铜",
        value=f"{gc['value']:.1f}",
        subtitle="避险资产相对工业金属",
        p1=gc.get("percentile_1y"),
        p3=gc.get("percentile_3y"),
        p5=gc.get("percentile_5y"),
        signal=gc["signal"],
    )
    metric_block(
        draw,
        890,
        name="10年美债",
        value=f"{ty['value']:.3f}%",
        subtitle="美国10年期国债收益率",
        p1=ty.get("percentile_1y"),
        p3=ty.get("percentile_3y"),
        p5=ty.get("percentile_5y"),
        signal=ty["signal"],
    )
    footer(draw, "数据来源：Yahoo Finance · 绝对值与历史分位并看")
    img.save(path, optimize=True)


def render_summary(data: dict[str, Any], path: Path) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), C["bg"])
    draw = ImageDraw.Draw(img)
    header(draw, "今日风险温度", "QQQ估值与综合信号", data["market_date"])
    qqq = data["valuation"]["nasdaq100"]
    overall = data["overall_signal"]

    rounded(draw, (70, 245, 1010, 655), radius=34)
    draw.text((110, 300), "纳斯达克100估值", font=f(42, True), fill=C["text"])
    draw.text((110, 385), "Trailing PE", font=f(25), fill=C["muted"])
    draw.text((470, 370), f"{qqq['trailing_pe']:.2f}x", font=f(52, True), fill=C["text"], anchor="ra")
    draw.text((570, 385), "Forward PE", font=f(25), fill=C["muted"])
    draw.text((950, 370), f"{qqq['forward_pe']:.2f}x", font=f(52, True), fill=C["blue"], anchor="ra")
    fpe_signal = detail_signal(data, "纳斯达克100 Forward PE")
    pill(draw, 110, 500, fpe_signal)
    draw.text((300, 514), f"估值覆盖率 {qqq.get('forward_pe_coverage', 0) * 100:.1f}%", font=f(23), fill=C["muted"])
    draw.text((950, 570), qqq.get("forward_pe_date", qqq.get("date", "")), font=f(19), fill=C["dim"], anchor="ra")

    rounded(draw, (70, 725, 1010, 1125), radius=34, outline=signal_color(overall["result"]))
    draw.text((540, 785), "综合判断", font=f(30), fill=C["muted"], anchor="ma")
    draw.text((540, 855), overall["result"], font=f(88, True), fill=signal_color(overall["result"]), anchor="ma")
    draw.text((540, 990), f"综合得分 {overall['score']:+d}", font=f(32, True), fill=C["text"], anchor="ma")

    for index, (label, key, color) in enumerate(
        (("偏买", "buy_count", C["green"]), ("中立", "neutral_count", C["yellow"]), ("偏卖", "sell_count", C["red"]))
    ):
        x = 70 + index * 330
        rounded(draw, (x, 1190, x + 280, 1365), radius=24, fill=C["panel2"], outline=color)
        draw.text((x + 140, 1230), label, font=f(25, True), fill=color, anchor="ma")
        draw.text((x + 140, 1295), str(overall[key]), font=f(54, True), fill=C["text"], anchor="ma")

    rounded(draw, (70, 1435, 1010, 1715), radius=28)
    draw.text((110, 1480), "本日有效信号", font=f(30, True), fill=C["text"])
    buy_reasons = [x for x in overall["details"] if x["signal"] == "偏买"]
    sell_reasons = [x for x in overall["details"] if x["signal"] == "偏卖"]
    y = 1540
    for item in (buy_reasons[:2] + sell_reasons[:1]):
        color = signal_color(item["signal"])
        draw.ellipse((112, y + 10, 128, y + 26), fill=color)
        draw.text((150, y), f"{item['indicator']}：{item['signal']}", font=f(23, True), fill=C["text"])
        y = draw_wrapped(
            draw,
            item["reason"],
            150,
            y + 38,
            font_obj=f(20),
            fill=C["muted"],
            width=760,
            max_lines=1,
        ) + 18

    footer(draw, "估值来源：weekly-etf-report / ETF_PE_history.xlsx")
    img.save(path, optimize=True)


def build_video(cards: list[Path], output: Path) -> None:
    if len(cards) != 4:
        raise ValueError("Exactly four cards are required.")

    with tempfile.TemporaryDirectory(prefix="market-risk-video-") as tmp:
        tmp_dir = Path(tmp)
        segments: list[Path] = []

        for index, card in enumerate(cards):
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
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/latest_data.json")
    parser.add_argument("--output-dir", default="output/media")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
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
    print(json.dumps({"cards": [str(x) for x in cards], "video": str(out / "market_risk_short.mp4")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
