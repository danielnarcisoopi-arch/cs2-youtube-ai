from __future__ import annotations

import asyncio
import html
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .scripts import VideoCopy

log = logging.getLogger(__name__)
W, H = 1080, 1920


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable '{name}' was not found in PATH")
    return path


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    options = (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else
               ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for p in options:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _skin_image(url: str | None, target: Path, timeout: int) -> bool:
    """Read the public Skinport item page's OpenGraph image. Never bypass bot controls."""
    if not url or urlparse(url).hostname not in {"skinport.com", "www.skinport.com"}:
        return False
    try:
        r = requests.get(url, headers={"User-Agent": "CS2-Market-Shorts/1.0", "Accept": "text/html"}, timeout=timeout)
        if r.status_code in (403, 429):
            log.info("Skinport item page declined image retrieval (HTTP %s)", r.status_code)
            return False
        r.raise_for_status()
        match = re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)', r.text, re.I)
        if not match:
            match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image', r.text, re.I)
        if not match:
            return False
        img_url = html.unescape(match.group(1))
        if urlparse(img_url).scheme != "https":
            return False
        image_response = requests.get(img_url, headers={"User-Agent": "CS2-Market-Shorts/1.0"}, timeout=timeout)
        image_response.raise_for_status()
        if len(image_response.content) > 12_000_000:
            return False
        target.write_bytes(image_response.content)
        with Image.open(target) as im:
            im.verify()
        return True
    except Exception as exc:
        log.warning("Could not retrieve marketplace image; using the designed fallback: %s", exc)
        target.unlink(missing_ok=True)
        return False


def _chart(points: list[tuple[str, float]], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8.0, 2.2), dpi=140)
    fig.patch.set_alpha(0)
    ax.set_facecolor((0.03, 0.06, 0.12, 0.0))
    if len(points) >= 2:
        xs = list(range(len(points)))
        ys = [v for _, v in points]
        ax.plot(xs, ys, color="#59E0B3", linewidth=3)
        ax.fill_between(xs, ys, min(ys), color="#59E0B3", alpha=0.14)
        ax.set_xticks([0, len(xs)-1], [points[0][0], points[-1][0]])
    else:
        ax.text(.5, .5, "Price history is building", color="white", ha="center", va="center", transform=ax.transAxes, fontsize=15)
        ax.set_xticks([])
    ax.tick_params(colors="#B8C4D4", labelsize=9, length=0)
    for spine in ax.spines.values(): spine.set_visible(False)
    ax.grid(axis="y", color="white", alpha=.13)
    fig.tight_layout(pad=.4)
    fig.savefig(path, transparent=True, bbox_inches="tight")
    plt.close(fig)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        test = f"{line} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= width:
            line = test
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)
    return lines


def make_card(copy: VideoCopy, currency: str, market_page: str | None, data_dir: Path,
              chart_points: list[tuple[str, float]], image_fetch: bool = True, image_timeout: int = 8) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    item = copy.featured
    bg = Image.new("RGB", (W, H), "#08111f")
    px = bg.load()
    for y in range(H):
        c = int(8 + 12 * y / H)
        for x in range(W): px[x, y] = (c, c + 7, c + 19)
    draw = ImageDraw.Draw(bg)
    draw.rounded_rectangle((50, 55, 1030, 1860), radius=42, fill="#0e1b2e", outline="#263b52", width=2)
    draw.text((90, 90), "CS2 MARKET BRIEF", font=_font(32, True), fill="#59E0B3")
    draw.text((90, 145), "LIVE MARKET DATA · SKINPORT", font=_font(20), fill="#a9b9ca")
    image_path = data_dir / "item-image.jpg"
    got_image = image_fetch and _skin_image(item.get("item_page"), image_path, image_timeout)
    image_box = (100, 220, 980, 750)
    if got_image:
        try:
            with Image.open(image_path) as source:
                im = ImageOps.contain(source.convert("RGB"), (830, 470))
            bg.paste(im, (W//2-im.width//2, 260+(440-im.height)//2))
        except Exception:
            got_image = False
    if not got_image:
        # Clean branded product panel when the market page doesn't expose an image.
        draw.rounded_rectangle(image_box, radius=28, fill="#122943", outline="#274663", width=2)
        draw.text((145, 400), "CS2 SKIN", font=_font(30, True), fill="#59E0B3")
        for idx, line in enumerate(_wrap(draw, item["name"], _font(39, True), 760)[:3]):
            draw.text((145, 455 + idx*54), line, font=_font(39, True), fill="white")
    name_lines = _wrap(draw, item["name"], _font(34, True), 890)[:2]
    yy = 790
    for line in name_lines:
        draw.text((90, yy), line, font=_font(34, True), fill="white")
        yy += 48
    draw.text((90, yy+20), f"{currency} {item['price']:.2f}", font=_font(58, True), fill="white")
    change = item.get("change_24h_pct")
    if change is None: change = item.get("change_7d_pct")
    change_text = "Building price history" if change is None else f"{change:+.2f}%"
    draw.rounded_rectangle((650, yy+8, 970, yy+105), radius=25, fill="#153d3c" if change is None or change >= 0 else "#4a242d")
    draw.text((690, yy+24), change_text, font=_font(39, True), fill="#59E0B3" if change is None or change >= 0 else "#ff8794")
    draw.text((95, 1040), "PRICE HISTORY · STORED SNAPSHOTS", font=_font(22, True), fill="#a9b9ca")
    chart_path = data_dir / "chart.png"
    _chart(chart_points, chart_path)
    try:
        with Image.open(chart_path).convert("RGBA") as chart:
            chart.thumbnail((890, 310))
            bg.paste(chart, (90, 1080), chart)
    except Exception:
        pass
    draw.text((95, 1425), f"24H SALES: {item.get('volume_24h', 0):,}", font=_font(27, True), fill="white")
    draw.text((95, 1475), f"LISTED: {item.get('quantity', 0):,}", font=_font(27, True), fill="#b7c7d8")
    draw.text((95, 1600), "MARKET DATA · NOT FINANCIAL ADVICE", font=_font(22, True), fill="#59E0B3")
    if market_page:
        draw.text((95, 1640), "Source: Skinport public market feed", font=_font(19), fill="#a9b9ca")
    path = data_dir / "card.png"
    bg.save(path)
    return path


def _srt_text(narration: str, duration: float) -> str:
    phrases = re.split(r"(?<=[.!?])\s+", narration.strip())
    phrases = [p for p in phrases if p]
    # Keep caption lines short enough for mobile. Timings are sentence-level estimates.
    chunks: list[str] = []
    for phrase in phrases:
        words = phrase.split()
        while words:
            chunks.append(" ".join(words[:9]))
            words = words[9:]
    weights = [max(1, len(c.split())) for c in chunks]
    total = sum(weights)
    cursor, blocks = 0.0, []
    for idx, (chunk, weight) in enumerate(zip(chunks, weights), 1):
        end = duration if idx == len(chunks) else cursor + duration * weight / total
        blocks.append(f"{idx}\n{_stamp(cursor)} --> {_stamp(end)}\n{chunk}\n")
        cursor = end
    return "\n".join(blocks)


def _stamp(seconds: float) -> str:
    ms = int(seconds * 1000)
    h, ms = divmod(ms, 3_600_000); m, ms = divmod(ms, 60_000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


async def _synthesize(text: str, voice: str, path: Path) -> Path:
    """Prefer Edge TTS, with a free local voice if Microsoft's endpoint is unavailable."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(path))
            return path
        except Exception as exc:
            last_error = exc
            path.unlink(missing_ok=True)
            if attempt == 0:
                log.warning("Edge-TTS failed; retrying once before using local speech: %s", exc)
                await asyncio.sleep(2)

    espeak = shutil.which("espeak-ng")
    if not espeak:
        raise RuntimeError(
            "Edge-TTS failed and the free local fallback 'espeak-ng' is not installed"
        ) from last_error

    # eSpeak NG is free and runs on the GitHub runner without an API key.
    # Map en-US-GuyNeural to the closest local English voice (en-us).
    voice_parts = voice.split("-")
    local_voice = "-".join(voice_parts[:2]).lower() if len(voice_parts) >= 2 else "en-us"
    fallback_path = path.with_suffix(".wav")
    subprocess.run(
        [espeak, "-v", local_voice, "-s", "150", "-w", str(fallback_path), text],
        check=True, capture_output=True, text=True,
    )
    log.warning("Edge-TTS unavailable after retry; generated narration with local voice %s", local_voice)
    return fallback_path


def render_video(copy: VideoCopy, currency: str, market_page: str | None, chart_points: list[tuple[str, float]],
                 data_dir: Path, output_path: Path, voice: str, image_fetch: bool = True,
                 image_timeout: int = 8) -> float:
    ffmpeg, ffprobe = require_binary("ffmpeg"), require_binary("ffprobe")
    data_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    card = make_card(copy, currency, market_page, data_dir, chart_points, image_fetch, image_timeout)
    audio = asyncio.run(_synthesize(copy.narration, voice, data_dir / "voice.mp3"))
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
                           check=True, capture_output=True, text=True)
    original_duration = float(probe.stdout.strip())
    if original_duration <= 0:
        raise RuntimeError("Edge-TTS generated empty audio")
    # Normalize narration to a 36-second Short while keeping an intelligible tempo.
    target = min(42.0, max(32.0, original_duration))
    atempo = original_duration / target
    srt = data_dir / "captions.srt"
    srt.write_text(_srt_text(copy.narration, target), encoding="utf-8")
    srt_arg = str(srt).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(card), "-i", str(audio),
        "-vf", f"zoompan=z='min(zoom+0.00035,1.08)':d={int(target*30)}:s=1080x1920:fps=30,subtitles='{srt_arg}':force_style='FontName=DejaVu Sans,FontSize=14,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV=230'",
        "-af", f"atempo={atempo:.5f},apad=pad_dur=0.2", "-t", f"{target:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output_path)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    verify = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=width,height", "-of", "default=noprint_wrappers=1", str(output_path)],
                            check=True, capture_output=True, text=True).stdout
    if "width=1080" not in verify or "height=1920" not in verify:
        raise RuntimeError(f"Rendered file is not 1080x1920: {verify}")
    duration = float(re.search(r"duration=([\d.]+)", verify).group(1))
    if duration < 30 or duration > 45:
        raise RuntimeError(f"Rendered Short duration outside 30-45 seconds: {duration:.2f}")
    return duration
