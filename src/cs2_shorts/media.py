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


def _skin_image(name: str, url: str | None, target: Path, timeout: int) -> bool:
    """Find this exact skin's image in a public CS2 catalog, then try Skinport OG."""
    try:
        # Skinport's API does not expose image URLs, and its web page may omit
        # OpenGraph images. Match the exact Steam market name in a public catalog.
        catalog_url = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins_not_grouped.json"
        response = requests.get(catalog_url, headers={"User-Agent": "CS2-Market-Shorts/1.0"}, timeout=(8, 45))
        response.raise_for_status()
        catalog = response.json()
        if isinstance(catalog, list):
            skin = next((row for row in catalog if row.get("market_hash_name") == name), None)
            image_url = skin.get("image") if skin else None
            if image_url and _download_image(image_url, target, timeout):
                return True
    except Exception as exc:
        log.info("Public skin catalog lookup unavailable; trying marketplace image: %s", exc)

    # Secondary fallback: public item page only. Do not bypass 403/429 controls.
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
        return bool(match and _download_image(html.unescape(match.group(1)), target, timeout))
    except Exception as exc:
        log.warning("Could not retrieve marketplace image; using the designed fallback: %s", exc)
        target.unlink(missing_ok=True)
        return False


def _download_image(image_url: str, target: Path, timeout: int) -> bool:
    if urlparse(image_url).scheme != "https":
        return False
    response = requests.get(image_url, headers={"User-Agent": "CS2-Market-Shorts/1.0"}, timeout=timeout)
    response.raise_for_status()
    if len(response.content) > 12_000_000:
        return False
    target.write_bytes(response.content)
    try:
        with Image.open(target) as im:
            im.verify()
        return True
    except Exception:
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


def make_scenes(copy: VideoCopy, currency: str, data_dir: Path,
                chart_points: list[tuple[str, float]], image_fetch: bool = True,
                image_timeout: int = 8) -> list[Path]:
    """Create three distinct vertical scenes instead of holding on one poster."""
    data_dir.mkdir(parents=True, exist_ok=True)
    item = copy.featured
    name = item["name"]
    image_path = data_dir / "item-image.jpg"
    got_image = image_fetch and _skin_image(name, item.get("item_page"), image_path, image_timeout)
    chart_path = data_dir / "chart-scenes.png"
    _chart(chart_points, chart_path)

    def canvas(index: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        bg = Image.new("RGB", (W, H), "#08111f")
        pix = bg.load()
        for y in range(H):
            for x in range(W):
                glow = int(8 * max(0, 1 - abs(x - (250 + index * 270)) / W))
                pix[x, y] = (8 + glow, 15 + glow, 29 + glow * 2)
        draw = ImageDraw.Draw(bg)
        draw.rounded_rectangle((45, 50, 1035, 1870), radius=48,
                               fill="#0e1b2e", outline="#263b52", width=2)
        draw.text((90, 90), "CS2 MARKET BRIEF", font=_font(30, True), fill="#59E0B3")
        return bg, draw

    def put_skin(bg: Image.Image, box: tuple[int, int, int, int]) -> bool:
        if not got_image:
            return False
        try:
            with Image.open(image_path) as source:
                art = ImageOps.contain(source.convert("RGBA"), (box[2] - box[0], box[3] - box[1]))
            bg.paste(art, (box[0] + (box[2] - box[0] - art.width) // 2,
                           box[1] + (box[3] - box[1] - art.height) // 2), art)
            return True
        except Exception as exc:
            log.info("Could not place skin artwork in video scene: %s", exc)
            return False

    scenes: list[Path] = []
    change = item.get("change_24h_pct")
    if change is None:
        change = item.get("change_7d_pct")
    change_label = "MARKET WATCH" if change is None else f"{change:+.1f}%"

    # Scene 1: fast hook with the featured skin artwork.
    bg, draw = canvas(0)
    draw.text((90, 190), "TODAY'S BIG MOVE", font=_font(29, True), fill="#a9b9ca")
    for idx, line in enumerate(_wrap(draw, name, _font(48, True), 850)[:3]):
        draw.text((90, 255 + idx * 66), line, font=_font(48, True), fill="white")
    draw.text((90, 500), change_label, font=_font(112, True), fill="#59E0B3" if change is None or change >= 0 else "#ff8794")
    draw.rounded_rectangle((80, 700, 1000, 1250), radius=38, fill="#122943", outline="#274663", width=2)
    if not put_skin(bg, (115, 735, 965, 1215)):
        draw.text((130, 850), "CS2 SKIN", font=_font(35, True), fill="#59E0B3")
        for idx, line in enumerate(_wrap(draw, name, _font(42, True), 750)[:3]):
            draw.text((130, 920 + idx * 58), line, font=_font(42, True), fill="white")
    draw.text((90, 1330), f"CURRENT LOW LISTING  {currency} {item['price']:.2f}", font=_font(31, True), fill="white")
    draw.text((90, 1760), "PRICE MOVES CAN REVERSE QUICKLY", font=_font(25, True), fill="#a9b9ca")
    scenes.append(data_dir / "scene-1.png")
    bg.save(scenes[-1])

    # Scene 2: market facts, sales activity and a different crop/scale of the image.
    bg, draw = canvas(1)
    draw.text((90, 200), "PRICE CHECK", font=_font(34, True), fill="#a9b9ca")
    if not put_skin(bg, (90, 300, 990, 870)):
        draw.rounded_rectangle((90, 300, 990, 870), radius=34, fill="#122943", outline="#274663", width=2)
        draw.text((140, 500), "LIVE SKINPORT SNAPSHOT", font=_font(34, True), fill="#59E0B3")
    draw.text((90, 940), f"{currency} {item['price']:.2f}", font=_font(83, True), fill="white")
    draw.text((95, 1060), "LOWEST CURRENT LISTING", font=_font(26, True), fill="#a9b9ca")
    draw.rounded_rectangle((85, 1180, 525, 1435), radius=28, fill="#122943")
    draw.text((125, 1220), f"{item.get('volume_24h', 0):,}", font=_font(64, True), fill="#59E0B3")
    draw.text((125, 1310), "SALES · 24H", font=_font(25, True), fill="white")
    draw.rounded_rectangle((555, 1180, 995, 1435), radius=28, fill="#122943")
    draw.text((595, 1220), f"{item.get('quantity', 0):,}", font=_font(64, True), fill="#59E0B3")
    draw.text((595, 1310), "LISTED NOW", font=_font(25, True), fill="white")
    draw.text((90, 1650), "MARKETPLACE FEES AFFECT SELLER RETURNS", font=_font(24, True), fill="#a9b9ca")
    scenes.append(data_dir / "scene-2.png")
    bg.save(scenes[-1])

    # Scene 3: price history takes over the frame, followed by a clear CTA.
    bg, draw = canvas(2)
    draw.text((90, 200), "TRACK THE PRICE", font=_font(34, True), fill="#a9b9ca")
    draw.text((90, 300), name[:44], font=_font(38, True), fill="white")
    try:
        with Image.open(chart_path).convert("RGBA") as chart:
            chart.thumbnail((900, 650))
            bg.paste(chart, (90, 470), chart)
    except Exception as exc:
        log.info("Could not place chart in final scene: %s", exc)
    if item.get("change_24h_pct") is not None:
        draw.text((95, 1210), f"24H CHANGE  {item['change_24h_pct']:+.2f}%", font=_font(39, True), fill="#59E0B3" if item["change_24h_pct"] >= 0 else "#ff8794")
    if item.get("change_7d_pct") is not None:
        draw.text((95, 1285), f"7D CHANGE  {item['change_7d_pct']:+.2f}%", font=_font(34, True), fill="white")
    draw.rounded_rectangle((85, 1480, 995, 1690), radius=32, fill="#153d3c")
    draw.text((130, 1542), "WOULD YOU BUY, SELL OR WAIT?", font=_font(35, True), fill="white")
    draw.text((95, 1760), "COMMENT BELOW · NOT FINANCIAL ADVICE", font=_font(23, True), fill="#59E0B3")
    scenes.append(data_dir / "scene-3.png")
    bg.save(scenes[-1])
    return scenes


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
    """Prefer Edge TTS; use a free neural Piper voice when its endpoint is unavailable."""
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

    piper_voice = "en_US-libritts_r-medium"
    fallback_path = path.with_suffix(".wav")
    try:
        subprocess.run(
            [shutil.which("python") or "python", "-m", "piper", "-m", piper_voice,
             "--data-dir", "data/voices", "-f", str(fallback_path), "--", text],
            check=True, capture_output=True, text=True, timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError("Edge-TTS failed and the free neural Piper fallback could not synthesize audio") from (exc or last_error)
    log.warning("Edge-TTS unavailable after retry; generated narration with Piper neural voice %s", piper_voice)
    return fallback_path


def render_video(copy: VideoCopy, currency: str, market_page: str | None, chart_points: list[tuple[str, float]],
                 data_dir: Path, output_path: Path, voice: str, image_fetch: bool = True,
                 image_timeout: int = 8) -> float:
    ffmpeg, ffprobe = require_binary("ffmpeg"), require_binary("ffprobe")
    data_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scenes = make_scenes(copy, currency, data_dir, chart_points, image_fetch, image_timeout)
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
    scene_durations = [target * 0.32, target * 0.38, target * 0.30]
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for scene, scene_duration in zip(scenes, scene_durations):
        command.extend(["-loop", "1", "-framerate", "30", "-t", f"{scene_duration:.3f}", "-i", str(scene)])
    audio_input = len(scenes)
    command.extend(["-i", str(audio)])
    filters: list[str] = []
    for index, scene_duration in enumerate(scene_durations):
        filters.append(
            f"[{index}:v]zoompan=z='min(zoom+0.00045,1.07)':d=1:s=1080x1920:fps=30,"
            f"trim=duration={scene_duration:.3f},setpts=PTS-STARTPTS[v{index}]"
        )
    concat_inputs = "".join(f"[v{i}]" for i in range(len(scenes)))
    subtitle_style = "FontName=DejaVu Sans,FontSize=14,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV=230"
    filters.append(f"{concat_inputs}concat=n={len(scenes)}:v=1:a=0,subtitles='{srt_arg}':force_style='{subtitle_style}'[vfinal]")
    command.extend(["-filter_complex", ";".join(filters), "-map", "[vfinal]", "-map", f"{audio_input}:a:0",
        "-af", f"atempo={atempo:.5f},apad=pad_dur=0.2", "-t", f"{target:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output_path)])
    subprocess.run(command, check=True, capture_output=True, text=True)
    verify = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=width,height", "-of", "default=noprint_wrappers=1", str(output_path)],
                            check=True, capture_output=True, text=True).stdout
    if "width=1080" not in verify or "height=1920" not in verify:
        raise RuntimeError(f"Rendered file is not 1080x1920: {verify}")
    duration = float(re.search(r"duration=([\d.]+)", verify).group(1))
    if duration < 30 or duration > 45:
        raise RuntimeError(f"Rendered Short duration outside 30-45 seconds: {duration:.2f}")
    return duration
