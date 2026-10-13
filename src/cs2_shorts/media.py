from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .scripts import VideoCopy

log = logging.getLogger(__name__)
W, H = 1080, 1920
INK = (5, 12, 22)
PANEL = (12, 24, 39)
GRID = (24, 42, 60)
WHITE = (242, 247, 250)
MUTED = (145, 164, 181)
MINT = (83, 232, 179)
RED = (255, 105, 121)
AMBER = (255, 191, 92)


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable '{name}' was not found in PATH")
    return path


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    choices = (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else
               ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for path in choices:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _skin_image(name: str, target: Path, timeout: int) -> bool:
    """Load only the exact catalog artwork; page-preview images can contain unwanted UI/text."""
    if target.exists():
        try:
            with Image.open(target) as image:
                image.verify()
            return True
        except Exception:
            target.unlink(missing_ok=True)
    try:
        catalog_url = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins_not_grouped.json"
        response = requests.get(catalog_url, headers={"User-Agent": "CS2-Market-Shorts/2.0"}, timeout=(8, 45))
        response.raise_for_status()
        catalog = response.json()
        if isinstance(catalog, list):
            row = next((entry for entry in catalog if entry.get("market_hash_name") == name), None)
            image_url = row.get("image") if row else None
            if image_url and _download_image(image_url, target, timeout):
                return True
    except Exception as exc:
        log.info("Exact catalog artwork unavailable; rendering a clean text-led hero: %s", exc)
    return False


def _download_image(image_url: str, target: Path, timeout: int) -> bool:
    if urlparse(image_url).scheme != "https":
        return False
    response = requests.get(image_url, headers={"User-Agent": "CS2-Market-Shorts/2.0"}, timeout=timeout)
    response.raise_for_status()
    if len(response.content) > 12_000_000:
        return False
    target.write_bytes(response.content)
    try:
        with Image.open(target) as image:
            image.verify()
        return True
    except Exception:
        target.unlink(missing_ok=True)
        return False


def _background(beat: int, minimal: bool = False) -> Image.Image:
    """Fast full-bleed vertical gradient and market-grid texture."""
    top = (8 + (beat % 3), 17, 29)
    bottom = (3, 9, 17)
    image = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(image)
    # One filled horizontal band per row avoids the old per-pixel Python loop.
    for y in range(H):
        t = y / max(1, H - 1)
        color = tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, W, y), fill=color)
    if not minimal:
        for x in range(36, W, 84):
            draw.line((x, 0, x, H), fill=GRID, width=1)
        for y in range(110, H, 84):
            draw.line((0, y, W, y), fill=GRID, width=1)
    draw.rectangle((0, 0, 8 if minimal else 15, H), fill=MINT)
    return image


def _wrapped(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _text(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], size: int,
          color: tuple[int, int, int] = WHITE, bold: bool = False, max_width: int = 900,
          line_gap: int = 14, max_lines: int = 3) -> int:
    font = _font(size, bold)
    y = xy[1]
    for line in _wrapped(draw, text, font, max_width)[:max_lines]:
        draw.text((xy[0], y), line, font=font, fill=color)
        y += size + line_gap
    return y


def _money(value: float | int | None, currency: str) -> str:
    return f"{currency} {value:,.2f}" if value is not None else "—"


def _change(item: dict[str, Any]) -> float | None:
    return item.get("change_24h_pct") if item.get("change_24h_pct") is not None else item.get("change_7d_pct")


def _chart(draw: ImageDraw.ImageDraw, points: list[tuple[str, float]], box: tuple[int, int, int, int],
           progress: float = 1, currency: str = "") -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=24, fill=PANEL, outline=(40, 61, 78), width=2)
    for i in range(1, 5):
        y = y1 + (y2 - y1) * i // 5
        draw.line((x1 + 24, y, x2 - 24, y), fill=GRID, width=2)
    usable = points[-30:]
    if len(usable) < 2:
        _text(draw, "PRICE HISTORY BUILDING", (x1 + 36, y1 + 85), 27, MUTED, True)
        return
    values = [max(0.0001, float(value)) for _, value in usable]
    low, high = min(values), max(values)
    span = high - low or max(high * .01, .01)
    count = max(2, round((len(values) - 1) * min(1.0, max(.05, progress))) + 1)
    coords = []
    for index, value in enumerate(values[:count]):
        x = x1 + 32 + round(index * (x2 - x1 - 64) / max(1, len(values) - 1))
        y = y2 - 45 - round((value - low) / span * (y2 - y1 - 100))
        coords.append((x, y))
    if len(coords) > 1:
        draw.line(coords, fill=MINT, width=7, joint="curve")
        x0, y0 = coords[0]
        draw.line((x0, y0, coords[-1][0], y2 - 40), fill=(20, 90, 75), width=1)
        draw.ellipse((coords[-1][0] - 10, coords[-1][1] - 10, coords[-1][0] + 10, coords[-1][1] + 10), fill=WHITE)
    _text(draw, f"RANGE  {_money(low, currency)} – {_money(high, currency)}", (x1 + 28, y1 + 24), 17, MUTED, True, max_width=560)
    left = usable[0][0]
    right = usable[-1][0]
    draw.text((x1 + 28, y2 - 34), left, font=_font(16, True), fill=MUTED)
    right_font = _font(16, True)
    right_width = draw.textbbox((0, 0), right, font=right_font)[2]
    draw.text((x2 - right_width - 28, y2 - 34), right, font=right_font, fill=MUTED)


def make_scenes(copy: VideoCopy, currency: str, data_dir: Path,
                chart_points: list[tuple[str, float]], image_fetch: bool = True,
                image_timeout: int = 8, beat_count: int = 10) -> list[Path]:
    """Render a broadcast-style story as short, data-driven visual beats."""
    data_dir.mkdir(parents=True, exist_ok=True)
    item = copy.featured
    name = item["name"]
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")[:70] or "skin"
    artwork = data_dir / f"item-{safe_name}.img"
    got_image = image_fetch and _skin_image(name, artwork, image_timeout)
    change = _change(item)
    polarity = MINT if change is None or change >= 0 else RED
    chart = list(chart_points)
    evidence_phases = ("tape", "chart", "spread", "flow")
    paths: list[Path] = []

    def item_art(image: Image.Image, box: tuple[int, int, int, int]) -> None:
        x1, y1, x2, y2 = box
        draw = ImageDraw.Draw(image)
        if got_image:
            try:
                with Image.open(artwork) as source:
                    art = source.convert("RGBA")
                    alpha = art.getchannel("A")
                    if alpha.getextrema() != (255, 255):
                        bounds = alpha.getbbox()
                        if bounds:
                            art = art.crop(bounds)
                    art = ImageOps.contain(art, (x2 - x1, y2 - y1), method=Image.Resampling.LANCZOS)
                px = x1 + (x2 - x1 - art.width) // 2
                py = y1 + (y2 - y1 - art.height) // 2
                shadow = Image.new("RGBA", art.size, (0, 0, 0, 0))
                shadow.putalpha(art.getchannel("A").filter(ImageFilter.GaussianBlur(22)).point(lambda value: value // 3))
                image.paste(shadow, (px + 9, py + 18), shadow)
                image.paste(art, (px, py), art)
                return
            except Exception as exc:
                log.info("Could not place skin artwork: %s", exc)
        _text(draw, "CLEAN ITEM ART UNAVAILABLE", (x1 + 60, (y1 + y2) // 2 - 20), 25, MUTED, True)

    total = max(1, beat_count)
    for index in range(total):
        if index == 0:
            phase = "alert"
        elif index == 1:
            phase = "signal"
        elif index == 2 and total > 4:
            phase = "reveal"
        elif index == total - 1:
            phase = "decision"
        else:
            phase = evidence_phases[(index - 3) % len(evidence_phases)]
        frame = _background(index, minimal=phase in {"reveal", "decision"})
        if phase == "reveal" and got_image:
            glow = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse((200, 290, 900, 1020), fill=(38, 155, 129, 46))
            glow = glow.filter(ImageFilter.GaussianBlur(115))
            frame = Image.alpha_composite(frame.convert("RGBA"), glow).convert("RGB")
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 0, W, 118), fill=(5, 13, 23))
        draw.text((48, 39), "CS2  /  MARKET SIGNAL", font=_font(25, True), fill=MINT)
        draw.text((745, 43), "SKINPORT SNAPSHOT", font=_font(19, True), fill=MUTED)
        draw.line((46, 120, 1030, 120), fill=(43, 64, 83), width=2)
        draw.rectangle((46, 1810, 1030, 1815), fill=(34, 53, 70))
        draw.rectangle((46, 1810, 46 + round(984 * (index + 1) / total), 1815), fill=MINT)
        draw.text((50, 1760), "SKINPORT DATA  •  MARKET INFORMATION, NOT A FORECAST",
                  font=_font(17, True), fill=MUTED)

        if phase == "alert":
            draw.text((62, 200), "PRICE ACTION", font=_font(26, True), fill=AMBER)
            _text(draw, "A MOVE WORTH\nA SECOND LOOK", (58, 320), 72, WHITE, True, max_width=920, line_gap=4)
            headline = f"{change:+.1f}%" if change is not None else "PRICE ≠ SALES"
            _text(draw, headline, (58, 620), 126, polarity, True)
            _text(draw, "The number is only half the story.", (62, 840), 33, MUTED, False)
            _chart(draw, chart, (48, 1090, 1028, 1570), progress=.24, currency=currency)
        elif phase == "signal":
            draw.text((62, 205), "THE SIGNAL", font=_font(25, True), fill=AMBER)
            _text(draw, "WHAT MOVED?", (58, 300), 65, WHITE, True)
            label = "24H CHANGE" if item.get("change_24h_pct") is not None else "7D CHANGE"
            _text(draw, label, (64, 530), 25, MUTED, True)
            _text(draw, f"{change:+.2f}%" if change is not None else "NO STORED COMPARISON",
                  (58, 600), 82 if change is not None else 43, polarity, True)
            _text(draw, "Measured against the nearest stored snapshot.", (64, 790), 27, MUTED)
            _chart(draw, chart, (48, 1030, 1028, 1575), progress=.42, currency=currency)
        elif phase == "reveal":
            draw.text((62, 205), "THE ITEM", font=_font(25, True), fill=AMBER)
            if got_image:
                item_art(frame, (48, 270, 1030, 1010))
                _text(draw, name, (62, 1060), 46, WHITE, True, max_width=940, max_lines=3)
                _text(draw, f"LOWEST LISTING  {_money(item.get('price'), currency)}", (62, 1260), 29, MINT, True)
                _text(draw, "MARKET ITEM · EXACT NAME MATCH", (62, 1340), 23, MUTED, True)
            else:
                _text(draw, name, (62, 430), 54, WHITE, True, max_width=940, max_lines=3)
                if change is not None:
                    _text(draw, f"{change:+.2f}%", (62, 680), 112, polarity, True)
                    _text(draw, "TRACKED PRICE CHANGE", (66, 810), 23, MUTED, True)
                _text(draw, f"LOWEST LISTING  {_money(item.get('price'), currency)}", (62, 1030), 34, MINT, True)
                _text(draw, "Exact catalog weapon artwork unavailable for this run.", (62, 1110), 25, MUTED)
        elif phase == "tape":
            draw.text((62, 205), "PRICE CHECK", font=_font(25, True), fill=AMBER)
            _text(draw, "LISTING PRICE", (62, 360), 25, MUTED, True)
            _text(draw, _money(item.get("price"), currency), (58, 410), 76, WHITE, True)
            draw.line((62, 570, 1018, 570), fill=(43, 64, 83), width=2)
            _text(draw, "AVERAGE SOLD · 24H", (62, 650), 25, MUTED, True)
            _text(draw, _money(item.get("avg_sale_24h"), currency), (58, 705), 68, MINT, True)
            _text(draw, "Lowest active listing and completed sales are different measures.",
                  (62, 900), 28, WHITE, False, max_width=900, max_lines=3)
            _chart(draw, chart, (48, 1190, 1028, 1600), progress=.58, currency=currency)
        elif phase == "chart":
            draw.text((62, 205), "PRICE HISTORY", font=_font(25, True), fill=AMBER)
            _text(draw, "FOLLOW THE LINE", (58, 300), 60, WHITE, True)
            _chart(draw, chart, (48, 520, 1028, 1320), progress=.76, currency=currency)
            if item.get("change_7d_pct") is not None:
                _text(draw, f"7D  {item['change_7d_pct']:+.2f}%", (64, 1400), 38,
                      MINT if item["change_7d_pct"] >= 0 else RED, True)
            _text(draw, "Historical snapshots are not a price forecast.", (64, 1500), 24, MUTED)
        elif phase == "spread":
            draw.text((62, 205), "SALES RANGE", font=_font(25, True), fill=AMBER)
            _text(draw, "WHERE TRADES LANDED", (58, 300), 53, WHITE, True)
            low, high = item.get("min_sale_24h"), item.get("max_sale_24h")
            _text(draw, _money(low, currency), (62, 550), 58, RED, True)
            draw.line((190, 735, 890, 735), fill=(66, 94, 112), width=14)
            draw.ellipse((177, 722, 203, 748), fill=RED)
            draw.ellipse((877, 722, 903, 748), fill=MINT)
            _text(draw, _money(high, currency), (610, 800), 58, MINT, True)
            _text(draw, f"{item.get('volume_24h', 0):,} REPORTED SALES · 24H", (62, 1050), 29, WHITE, True)
            _chart(draw, chart, (48, 1240, 1028, 1600), progress=.90, currency=currency)
        elif phase == "flow":
            draw.text((62, 205), "MARKET ACTIVITY", font=_font(25, True), fill=AMBER)
            _text(draw, "IS THERE DEPTH?", (58, 300), 62, WHITE, True)
            _text(draw, f"{item.get('volume_24h', 0):,}", (62, 550), 100, MINT, True)
            _text(draw, "REPORTED SALES · 24H", (65, 680), 24, MUTED, True)
            _text(draw, f"{item.get('quantity', 0):,}", (62, 870), 78, WHITE, True)
            _text(draw, "CURRENT LISTINGS", (65, 980), 24, MUTED, True)
            _text(draw, "Volume is activity, not a guarantee of liquidity at every price.",
                  (62, 1200), 28, WHITE, False, max_width=900, max_lines=3)
        else:
            draw.text((62, 205), "YOUR CALL", font=_font(25, True), fill=AMBER)
            _text(draw, "BUY. SELL.\nOR WAIT?", (58, 340), 80, WHITE, True, line_gap=4)
            _text(draw, name, (62, 650), 38, MINT, True, max_width=920, max_lines=3)
            _text(draw, "Comment your call—and the signal that convinced you.",
                  (62, 920), 34, WHITE, False, max_width=900, max_lines=3)
            _chart(draw, chart, (48, 1200, 1028, 1590), progress=1, currency=currency)

        path = data_dir / f"beat-{index + 1:02}.png"
        frame.save(path, optimize=True)
        paths.append(path)
    return paths


def _stamp(seconds: float) -> str:
    ms = max(0, int(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def _srt_text(narration: str, duration: float) -> str:
    """Keep caption beats short and aligned to sentence boundaries where possible."""
    phrases = re.split(r"(?<!\d)(?<=[.!?])\s+", narration.strip())
    chunks: list[str] = []
    for phrase in phrases:
        words = phrase.split()
        while words:
            chunks.append(" ".join(words[:6]))
            words = words[6:]
    if not chunks:
        return ""
    weights = [max(1, len(chunk.split())) + (0.35 if chunk.endswith((".", "!", "?")) else 0) for chunk in chunks]
    total = sum(weights)
    cursor = 0.0
    blocks = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights), 1):
        end = duration if index == len(chunks) else cursor + duration * weight / total
        blocks.append(f"{index}\n{_stamp(cursor)} --> {_stamp(end)}\n{chunk}\n")
        cursor = end
    return "\n".join(blocks)


async def _synthesize(text: str, voice: str, path: Path) -> Path:
    """Prefer Edge TTS; use the installed neural Piper voice if the endpoint fails."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            await edge_tts.Communicate(text, voice).save(str(path))
            return path
        except Exception as exc:
            last_error = exc
            path.unlink(missing_ok=True)
            if attempt == 0:
                log.warning("Edge TTS failed; retrying before local speech: %s", exc)
                await asyncio.sleep(2)

    fallback = path.with_suffix(".wav")
    command = [shutil.which("python") or "python", "-m", "piper", "-m", "en_US-libritts_r-medium",
               "--data-dir", "data/voices", "-f", str(fallback), "--", text]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError("Edge TTS failed and the Piper neural voice could not synthesize speech") from (exc or last_error)
    log.warning("Edge TTS unavailable; generated narration with Piper LibriTTS-R")
    return fallback


def render_video(copy: VideoCopy, currency: str, market_page: str | None, chart_points: list[tuple[str, float]],
                 data_dir: Path, output_path: Path, voice: str, image_fetch: bool = True,
                 image_timeout: int = 8) -> float:
    ffmpeg, ffprobe = require_binary("ffmpeg"), require_binary("ffprobe")
    data_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio = asyncio.run(_synthesize(copy.narration, voice, data_dir / "voice.mp3"))
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", str(audio)],
                           check=True, capture_output=True, text=True)
    original_duration = float(probe.stdout.strip())
    if original_duration <= 0:
        raise RuntimeError("Speech synthesis generated empty audio")
    # Keep the synthesized performance at natural speed; use short copy to control runtime.
    target = original_duration
    speed = 1.0
    beat_seconds = 2.0
    beat_count = max(1, min(18, round(target / beat_seconds)))
    scenes = make_scenes(copy, currency, data_dir, chart_points, image_fetch, image_timeout, beat_count)
    scene_duration = target / len(scenes)
    srt = data_dir / "captions.srt"
    srt.write_text(_srt_text(copy.narration, target), encoding="utf-8")
    srt_arg = str(srt).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for scene in scenes:
        command.extend(["-loop", "1", "-framerate", "30", "-t", f"{scene_duration:.4f}", "-i", str(scene)])
    audio_input = len(scenes)
    command.extend(["-i", str(audio)])
    filters: list[str] = []
    for index in range(len(scenes)):
        filters.append(
            f"[{index}:v]zoompan=z='min(zoom+0.00035,1.045)':"
            f"x='iw/2-(iw/zoom/2)+2*sin(on/24)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,"
            f"trim=duration={scene_duration:.4f},setpts=PTS-STARTPTS,setsar=1[v{index}]"
        )
    concat_inputs = "".join(f"[v{i}]" for i in range(len(scenes)))
    subtitle_style = ("FontName=DejaVu Sans,FontSize=19,PrimaryColour=&H00FFFFFF,"
                      "OutlineColour=&HCC07111D,BorderStyle=1,Outline=3,Shadow=0,"
                      "Alignment=2,MarginL=90,MarginR=90,MarginV=200")
    item = copy.featured
    ticker_text = (f"LOWEST ASK {_money(item.get('price'), currency)}  /  "
                   f"SOLD AVG {_money(item.get('avg_sale_24h'), currency)}  /  "
                   f"24H SALES {item.get('volume_24h', 0):,}  /  "
                   f"LISTED {item.get('quantity', 0):,}   ")
    ticker_text = (ticker_text.replace("\\", "\\\\").replace(":", "\\:")
                   .replace("'", "\\'").replace(",", "\\,").replace("%", "\\%"))
    fontfile = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ticker = (f"drawtext=fontfile='{fontfile}':text='{ticker_text}':"
              "x='w-mod(t*150\\,w+text_w)':y=139:fontsize=20:fontcolor=0x53E8B3:"
              "box=1:boxcolor=0x050D17@0.94:boxborderw=10")
    filters.append(f"{concat_inputs}concat=n={len(scenes)}:v=1:a=0,"
                   f"subtitles='{srt_arg}':force_style='{subtitle_style}',{ticker}[vfinal]")
    audio_filter = f"atempo={speed:.5f},apad=pad_dur=0.15"
    command.extend(["-filter_complex", ";".join(filters), "-map", "[vfinal]", "-map", f"{audio_input}:a:0",
                    "-af", audio_filter, "-t", f"{target:.3f}", "-r", "30", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-b:a", "160k", "-movflags", "+faststart", str(output_path)])
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        log.error("FFmpeg render failed: %s", exc.stderr[-4000:] if exc.stderr else exc)
        raise
    verify = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=width,height",
                             "-of", "default=noprint_wrappers=1", str(output_path)],
                            check=True, capture_output=True, text=True).stdout
    if "width=1080" not in verify or "height=1920" not in verify:
        raise RuntimeError(f"Rendered file is not 1080x1920: {verify}")
    match = re.search(r"duration=([\d.]+)", verify)
    duration = float(match.group(1)) if match else 0
    if duration < 12 or duration > 45:
        raise RuntimeError(f"Rendered Short duration outside 12–45 seconds: {duration:.2f}")
    return duration
