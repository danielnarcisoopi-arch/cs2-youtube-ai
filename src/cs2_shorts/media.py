from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .scripts import VideoCopy, _spoken_name
from .promotion import PROMO_MESSAGE

log = logging.getLogger(__name__)
W, H = 1080, 1920
INK = (7, 10, 17)
WHITE = (248, 249, 251)
MUTED = (167, 178, 190)
LIME = (151, 255, 80)
RED = (255, 93, 105)


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable '{name}' was not found in PATH")
    return path


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _text(draw: ImageDraw.ImageDraw, value: str, xy: tuple[int, int], size: int,
          color: tuple[int, int, int] = WHITE, bold: bool = False,
          anchor: str | None = None, stroke: int = 0) -> None:
    draw.text(xy, value, font=_font(size, bold), fill=color, anchor=anchor,
              stroke_width=stroke, stroke_fill=INK if stroke else None)


def _wrap_name(name: str, max_width: int = 930, size: int = 43) -> list[str]:
    font = _font(size, True)
    lines: list[str] = []
    line = ""
    for word in name.split():
        test = f"{line} {word}".strip()
        if ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), test, font=font)[2] <= max_width:
            line = test
        elif line:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines[:2]


def _skin_image(name: str, target: Path, timeout: int) -> bool:
    """Use a single exact-match weapon cutout, never a marketplace screenshot."""
    import requests
    if target.exists():
        try:
            with Image.open(target) as image:
                image.verify()
            return True
        except Exception:
            target.unlink(missing_ok=True)
    try:
        rows = _skin_catalog(target.parent, timeout)
        row = next((entry for entry in rows if entry.get("market_hash_name") == name), None) if isinstance(rows, list) else None
        image_url = row.get("image") if row else None
        if image_url and urlparse(image_url).scheme == "https":
            image = requests.get(image_url, headers={"User-Agent": "CS2-Market-Shorts/3.0"}, timeout=timeout)
            image.raise_for_status()
            if len(image.content) <= 12_000_000:
                target.write_bytes(image.content)
                with Image.open(target) as check:
                    check.verify()
                return True
    except Exception as exc:
        log.info("Exact weapon art unavailable; using the clean typographic fallback: %s", exc)
    return False


def _skin_catalog(data_dir: Path, timeout: int) -> list[dict]:
    """Load the canonical weapon-skin catalog, using its cache during outages."""
    import requests
    data_dir.mkdir(parents=True, exist_ok=True)
    cache = data_dir / "skins-catalog.json"
    cached = None
    if cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
    if isinstance(cached, list) and time.time() - cache.stat().st_mtime < 7 * 24 * 60 * 60:
        return cached
    try:
        url = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins_not_grouped.json"
        response = requests.get(url, headers={"User-Agent": "CS2-Market-Shorts/3.0"}, timeout=(8, max(8, timeout)))
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Weapon catalog response is not a list")
        cache.write_text(json.dumps(rows), encoding="utf-8")
        return rows
    except Exception as exc:
        if isinstance(cached, list):
            log.warning("Using the cached weapon catalog after a refresh failure: %s", exc)
            return cached
        log.error("Could not load the canonical weapon catalog: %s", exc)
        return []


def filter_rankings_to_weapon_skins(ranked: dict[str, list[dict]], data_dir: Path,
                                    timeout: int = 8) -> dict[str, list[dict]]:
    """Keep only catalog rows that can be rendered as a weapon POV scene."""
    catalog = _skin_catalog(data_dir, timeout)
    if not catalog:
        raise RuntimeError("The CS2 weapon artwork catalog is unavailable; refusing to select items without verified weapon images")
    from .skinshotter import supports_weapon_pov

    valid_names = {
        entry.get("market_hash_name") for entry in catalog
        if entry.get("market_hash_name") and supports_weapon_pov(entry)
    }
    filtered = {topic: [item for item in items if item.get("name") in valid_names]
                for topic, items in ranked.items()}
    removed = sum(len(items) - len(filtered[topic]) for topic, items in ranked.items())
    if removed:
        log.info("Skipped %d non-weapon or unsupported market items without canonical weapon artwork", removed)
    if not any(filtered.values()):
        raise RuntimeError("No ranked Skinport items matched the canonical weapon-skin catalog")
    return filtered


def _background(beat: int, accent: tuple[int, int, int] = LIME,
                art_path: Path | None = None) -> Image.Image:
    """Full-bleed charcoal, a soft color bloom, and no grid, panels, or dashboard frame."""
    image = Image.new("RGB", (W, H), INK)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shift = (beat % 5 - 2) * 45
    ImageDraw.Draw(glow).ellipse((120 + shift, 280, 1050 + shift, 1290), fill=(*accent, 56))
    glow = glow.filter(ImageFilter.GaussianBlur(185))
    result = Image.alpha_composite(image.convert("RGBA"), glow)
    if art_path is not None:
        try:
            with Image.open(art_path) as source:
                silhouette = source.convert("RGBA")
            alpha = silhouette.getchannel("A")
            if alpha.getextrema() != (255, 255):
                bounds = alpha.getbbox()
                if bounds:
                    silhouette = silhouette.crop(bounds)
                silhouette = ImageOps.contain(silhouette, (W + 180, 920), method=Image.Resampling.LANCZOS)
                silhouette = silhouette.filter(ImageFilter.GaussianBlur(72))
                silhouette.putalpha(silhouette.getchannel("A").point(lambda value: value // 5))
                x = (W - silhouette.width) // 2 + shift
                result.alpha_composite(silhouette, (x, 430))
        except Exception as exc:
            log.debug("Could not create soft weapon backdrop: %s", exc)
    return result.convert("RGB")


def _money(value: float | int | None, currency: str) -> str:
    if value is None:
        return "—"
    symbol = {"EUR": "€", "USD": "$", "GBP": "£"}.get(currency.upper(), currency + " ")
    return f"{symbol}{value:,.2f}"


def _hook_overlay(copy: VideoCopy, currency: str) -> tuple[str, str]:
    """Return one compact, evidence-backed headline for the cold open."""
    item = copy.featured
    if copy.hook_variant == "price_gap":
        price, average = item.get("price"), item.get("avg_sale_24h")
        if price is not None and average and average > 0:
            gap = (price / average - 1) * 100
            if gap >= 1:
                return f"{gap:.1f}%", "ASK ABOVE RECENT SALES"
            if gap <= -1:
                return f"{abs(gap):.1f}%", "ASK BELOW RECENT SALES"
            return "UNDER 1%", "ASK AND SALES ARE ALIGNED"
    if copy.topic == "gainers" and item.get("change_24h_pct") is not None:
        return f"+{item['change_24h_pct']:.1f}%", "IN 24 HOURS"
    if copy.topic == "losers" and item.get("change_24h_pct") is not None:
        return f"{item['change_24h_pct']:.1f}%", "IN 24 HOURS"
    if copy.topic == "weekly" and item.get("change_7d_pct") is not None:
        change = item["change_7d_pct"]
        return f"{change:+.1f}%", "THIS WEEK"
    if copy.topic == "budget":
        return _money(item.get("price"), currency), f"LOWEST ASK · {item.get('volume_24h', 0)} SALES TODAY"
    if copy.topic == "dollar_volume":
        return f"{item.get('volume_24h', 0)} SALES", "REPORTED IN 24 HOURS"
    if copy.topic == "volatility" and item.get("volatility_pct") is not None:
        return f"{item['volatility_pct']:.1f}%", "REPORTED SALE PRICE RANGE"
    return "MARKET WATCH", "A CS2 SKIN TO KEEP AN EYE ON"


def _draw_weapon(frame: Image.Image, art_path: Path | None, box: tuple[int, int, int, int],
                 scale: float = 1.0) -> None:
    if art_path is None:
        return
    try:
        with Image.open(art_path) as source:
            art = source.convert("RGBA")
        alpha = art.getchannel("A")
        if alpha.getextrema() != (255, 255):
            bounds = alpha.getbbox()
            if bounds:
                art = art.crop(bounds)
        x1, y1, x2, y2 = box
        # Scale never exceeds the safe box: a weapon must not be cropped by the canvas edge.
        safe_scale = min(max(scale, 0.1), 0.90)
        size = (int((x2 - x1) * safe_scale), int((y2 - y1) * safe_scale))
        art = ImageOps.contain(art, size, method=Image.Resampling.LANCZOS)
        px = (x1 + x2 - art.width) // 2
        py = (y1 + y2 - art.height) // 2
        shadow = Image.new("RGBA", art.size, (0, 0, 0, 0))
        shadow.putalpha(art.getchannel("A").filter(ImageFilter.GaussianBlur(26)).point(lambda a: a // 3))
        frame.paste(shadow, (px + 4, py + 17), shadow)
        frame.paste(art, (px, py), art)
    except Exception as exc:
        log.info("Could not render exact weapon art: %s", exc)


def make_scenes(copy: VideoCopy, currency: str, data_dir: Path,
                image_fetch: bool = True, image_timeout: int = 8) -> list[Path]:
    """Create matching promo, skin-price, and promo-outro scenes."""
    if copy.series == "editorial":
        from .editorial_visuals import make_editorial_scenes
        return make_editorial_scenes(copy, currency, data_dir, image_timeout)
    data_dir.mkdir(parents=True, exist_ok=True)
    items = (copy.items or [copy.featured])[:5]
    art_paths: list[Path] = []
    for item in items:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", item["name"]).strip("-")[:70] or "skin"
        art = data_dir / f"weapon-{safe}.img"
        if not image_fetch or not _skin_image(item["name"], art, image_timeout):
            raise RuntimeError(f"Exact catalog artwork is unavailable for {item['name']}; refusing to publish an empty weapon showcase")
        art_paths.append(art)
    phases = ["promo-intro", *[f"item-{i}" for i in range(len(items))], "promo-outro"]
    paths: list[Path] = []

    for index, phase in enumerate(phases):
        current_index = int(phase.split("-", 1)[1]) if phase.startswith("item-") else 0
        art_path = art_paths[current_index]
        frame = _background(index, LIME, art_path)
        draw = ImageDraw.Draw(frame)
        # A tiny recurring mark gives the sequence identity without a permanent header/footer.
        draw.ellipse((54, 66, 70, 82), fill=LIME)
        _text(draw, "CS2 MARKET", (88, 72), 19, MUTED, True, anchor="lm")

        if phase in {"promo-intro", "promo-outro"}:
            _draw_weapon(frame, art_path, (70, 890, 1010, 1480), .86)
            draw.rounded_rectangle((48, 250, 1032, 820), radius=40,
                                   fill=(5, 9, 15), outline=LIME, width=6)
            promo_title, promo_cta = PROMO_MESSAGE.split(", ", 1)
            _text(draw, promo_title + ",", (540, 405), 76, LIME, True, anchor="mm")
            _text(draw, promo_cta, (540, 525), 49, WHITE, True, anchor="mm")
            draw.rounded_rectangle((142, 625, 938, 710), radius=24,
                                   fill=(24, 35, 28), outline=LIME, width=2)
            _text(draw, "clash.gg/r/CSSKINNS", (540, 668), 36, LIME, True, anchor="mm")
            label = "START HERE" if phase == "promo-intro" else "CLAIM YOUR FREE SKIN"
            _text(draw, label, (540, 765), 21, MUTED, True, anchor="mm")
        elif phase.startswith("item-"):
            item = items[current_index]
            _draw_weapon(frame, art_path, (15, 260, 1065, 1270), 1.12)
            _text(draw, f"{current_index + 1:02d} / {len(items):02d}", (58, 205), 22, LIME, True)
            name_lines = _wrap_name(item["name"], size=41)
            for line_no, line in enumerate(name_lines):
                _text(draw, line, (58, 1390 + line_no * 54), 41, WHITE, True)
            price_y = 1545 if len(name_lines) > 1 else 1505
            _text(draw, _money(item.get("price"), currency), (60, price_y), 67, LIME, True)
        path = data_dir / f"beat-{index + 1:02}.png"
        frame.save(path, optimize=True)
        paths.append(path)
    return paths


async def _synthesize(text: str, voice: str, path: Path) -> Path:
    """Prefer a premium natural voice when configured, then Edge neural, then local Piper."""
    import requests
    import edge_tts
    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")
    if api_key and voice_id:
        try:
            response = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_multilingual_v2",
                      "voice_settings": {"stability": 0.34, "similarity_boost": 0.76,
                                         "style": 0.46, "use_speaker_boost": True}},
                timeout=(10, 90),
            )
            response.raise_for_status()
            path.write_bytes(response.content)
            log.info("Narration synthesized with the configured premium voice")
            return path
        except Exception as exc:
            path.unlink(missing_ok=True)
            log.warning("Configured premium voice failed; using neural fallback: %s", exc)
    last_error: Exception | None = None
    rate = os.getenv("EDGE_TTS_RATE", "+0%").strip()
    pitch = os.getenv("EDGE_TTS_PITCH", "+0Hz").strip()
    for attempt in range(2):
        try:
            await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume="+0%").save(str(path))
            return path
        except Exception as exc:
            last_error = exc
            path.unlink(missing_ok=True)
            if attempt == 0:
                log.warning("Neural voice service failed; retrying: %s", exc)
                await asyncio.sleep(2)
    fallback = path.with_suffix(".wav")
    command = [shutil.which("python") or "python", "-m", "piper", "-m", "en_US-libritts_r-medium",
               "--data-dir", "data/voices", "-f", str(fallback), "--", text]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError("Neural voice service failed and the local voice could not synthesize speech") from (exc or last_error)
    log.warning("Neural voice service unavailable; used local Piper fallback")
    return fallback


def _music_input(ffmpeg: str, duration: float, data_dir: Path) -> tuple[list[str], str]:
    """Use a supplied cleared track or generate a restrained original ambient bed."""
    supplied = os.getenv("CS2_MUSIC_PATH")
    fade_start = max(0, duration - .8)
    if supplied and Path(supplied).is_file():
        music_filter = (f"loudnorm=I=-26:TP=-2:LRA=7,afade=t=in:st=0:d=0.8,"
                        f"afade=t=out:st={fade_start:.3f}:d=0.8")
        return ["-stream_loop", "-1", "-i", supplied], music_filter
    path = data_dir / "ambient-market-bed.wav"
    # Original low-volume chord bed with a gentle pulse; no third-party music asset/license needed.
    # A restrained two-chord progression with a soft pulse. A supplied,
    # licensed track takes precedence; this is the self-contained fallback.
    root = "if(lt(mod(t,8),4),110,130.81)"
    third = "if(lt(mod(t,8),4),164.81,196)"
    fifth = "if(lt(mod(t,8),4),220,261.63)"
    expression = ("0.045*sin(2*PI*55*t)*(0.76+0.24*cos(2*PI*0.5*t))+"
                  f"0.019*sin(2*PI*{root}*t)+0.015*sin(2*PI*{third}*t)+"
                  f"0.012*sin(2*PI*{fifth}*t)+"
                  "0.010*sin(2*PI*440*t)*exp(-mod(t,0.8)*5)")
    expression = expression.replace(",", r"\,")
    source = f"aevalsrc=exprs={expression}:sample_rate=44100:duration={duration + 1:.3f}"
    fade_start = max(0, duration - .8)
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", source,
                    "-af", f"tremolo=f=0.16:d=0.18,afade=t=in:st=0:d=0.8,afade=t=out:st={fade_start:.3f}:d=0.8",
                    "-c:a", "pcm_s16le", str(path)], check=True, capture_output=True, text=True)
    return ["-i", str(path)], "loudnorm=I=-26:TP=-2:LRA=7"


def _pov_overlay(copy: VideoCopy, currency: str, phase: str, index: int,
                 total: int, output: Path) -> Path:
    """Create sparse, high-contrast labels over live POV footage."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    # Keep all text in the upper-left map space, away from the lower-right gun viewmodel.
    draw.rounded_rectangle((44, 54, 320, 108), radius=18, fill=(5, 9, 15, 190))
    draw.ellipse((60, 73, 74, 87), fill=LIME)
    _text(draw, "CS2  /  MARKET", (90, 81), 20, WHITE, True, anchor="lm")

    if phase in {"promo-intro", "promo-outro"}:
        draw.rounded_rectangle((42, 430, 1038, 1030), radius=40,
                               fill=(5, 9, 15, 238), outline=(*LIME, 255), width=6)
        promo_title, promo_cta = PROMO_MESSAGE.split(", ", 1)
        _text(draw, promo_title + ",", (540, 600), 76, LIME, True, anchor="mm")
        _text(draw, promo_cta, (540, 730), 48, WHITE, True, anchor="mm")
        draw.rounded_rectangle((142, 820, 938, 905), radius=24,
                               fill=(24, 35, 28, 245), outline=(*LIME, 255), width=2)
        _text(draw, "clash.gg/r/CSSKINNS", (540, 863), 36, LIME, True, anchor="mm")
        label = "START HERE" if phase == "promo-intro" else "CLAIM YOUR FREE SKIN"
        _text(draw, label, (540, 967), 21, MUTED, True, anchor="mm")
    elif phase == "item":
        item = (copy.items or [copy.featured])[index]
        draw.rounded_rectangle((44, 136, 850, 410), radius=28, fill=(4, 8, 13, 155))
        _text(draw, f"{index + 1:02d}  /  {total:02d}", (80, 174), 23, LIME, True)
        name_lines = _wrap_name(_base_skin_name(item["name"]), max_width=735, size=40)
        for line_no, line in enumerate(name_lines):
            _text(draw, line, (80, 220 + line_no * 50), 40, WHITE, True)
        _text(draw, _money(item.get("price"), currency), (80, 337), 48, LIME, True)
    else:
        draw.rounded_rectangle((44, 136, 870, 340), radius=28, fill=(4, 8, 13, 155))
        _text(draw, "BUY  OR  PASS?", (80, 184), 64, WHITE, True)
        _text(draw, "WHICH SKIN WOULD YOU EQUIP?", (82, 276), 24, LIME, True)

    output.parent.mkdir(parents=True, exist_ok=True)
    layer.save(output)
    return output


def _base_skin_name(name: str) -> str:
    value = re.sub(r"\s*\((?:Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)$", "", name, flags=re.I)
    return re.sub(r"^(?:StatTrak™?\s+|Souvenir\s+|★\s*)", "", value).strip()


def _render_pov_video(ffmpeg: str, ffprobe: str, copy: VideoCopy, currency: str,
                      data_dir: Path, output_path: Path, audio: Path, duration: float,
                      clip_paths: list[Path], scene_durations: list[float]) -> float:
    """Cut captured Skinshotter POV clips together with restrained overlays and audio."""
    items = (copy.items or [copy.featured])[:5]
    if len(clip_paths) != len(items) or not clip_paths:
        raise RuntimeError("POV renderer did not return one clip for each selected skin")
    segment_count = len(items) + 2
    if len(scene_durations) != segment_count or abs(sum(scene_durations) - duration) > .05:
        raise RuntimeError("Narration segments do not align with POV scene timing")
    overlays: list[Path] = []
    for scene_index in range(segment_count):
        if scene_index == 0:
            phase, item_index = "promo-intro", 0
            clip = clip_paths[0]
        elif scene_index == segment_count - 1:
            phase, item_index = "promo-outro", len(items) - 1
            clip = clip_paths[-1]
        else:
            phase, item_index = "item", scene_index - 1
            clip = clip_paths[item_index]
        overlay = _pov_overlay(copy, currency, phase, item_index, len(items),
                               data_dir / f"pov-overlay-{scene_index + 1:02d}.png")
        overlays.append(overlay)

    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for scene_index in range(segment_count):
        clip = clip_paths[0] if scene_index == 0 else clip_paths[-1] if scene_index == segment_count - 1 else clip_paths[scene_index - 1]
        command.extend(["-stream_loop", "-1", "-i", str(clip)])
    for scene_index, overlay in enumerate(overlays):
        command.extend(["-loop", "1", "-framerate", "30", "-t", f"{scene_durations[scene_index]:.4f}", "-i", str(overlay)])
    audio_input = segment_count * 2
    command.extend(["-i", str(audio)])
    music_args, music_filter = _music_input(ffmpeg, duration, data_dir)
    music_input = audio_input + 1
    command.extend(music_args)

    filters: list[str] = []
    for index in range(segment_count):
        filters.append(
            f"[{index}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"fps=30,trim=duration={scene_durations[index]:.4f},setpts=PTS-STARTPTS,setsar=1[base{index}]"
        )
        overlay_input = segment_count + index
        filters.append(
            f"[{overlay_input}:v]format=rgba,trim=duration={scene_durations[index]:.4f},"
            f"setpts=PTS-STARTPTS[overlay{index}]"
        )
        filters.append(f"[base{index}][overlay{index}]overlay=0:0:shortest=1[v{index}]")
    concat_inputs = "".join(f"[v{i}]" for i in range(segment_count))
    filters.append(f"{concat_inputs}concat=n={segment_count}:v=1:a=0[vfinal]")
    filters.append(f"[{audio_input}:a]aresample=44100,apad=whole_dur={duration:.3f},loudnorm=I=-16:TP=-1.5:LRA=10[voice]")
    filters.append(f"[{music_input}:a]{music_filter}[bed]")
    filters.extend([
        "[voice]asplit=2[voice_mix][voice_key]",
        "[bed][voice_key]sidechaincompress=threshold=0.025:ratio=7:attack=12:release=280:makeup=1[ducked_bed]",
        "[voice_mix][ducked_bed]amix=inputs=2:duration=first:weights='1 0.75':normalize=0,alimiter=limit=0.95[aout]",
    ])
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[vfinal]", "-map", "[aout]",
        "-t", f"{duration:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "medium",
        "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output_path),
    ])
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        log.error("FFmpeg POV render failed: %s", exc.stderr[-4000:] if exc.stderr else exc)
        raise
    verify = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=width,height",
         "-of", "default=noprint_wrappers=1", str(output_path)],
        check=True, capture_output=True, text=True,
    ).stdout
    if "width=1080" not in verify or "height=1920" not in verify:
        raise RuntimeError(f"POV render is not 1080x1920: {verify}")
    match = re.search(r"duration=([\d.]+)", verify)
    final_duration = float(match.group(1)) if match else 0
    if final_duration < 12 or final_duration > 45:
        raise RuntimeError(f"Rendered Short duration outside 12–45 seconds: {final_duration:.2f}")
    return final_duration


def _voiceover_lines(copy: VideoCopy, currency: str) -> list[str]:
    """Build one spoken beat for each matching promo or skin-price scene."""
    if copy.scene_lines:
        if len(copy.scene_lines) != len(copy.items) + 2:
            raise ValueError("Editorial speech must match the hook, item scenes and outro")
        return copy.scene_lines
    items = (copy.items or [copy.featured])[:5]
    lines = ["Get a ten dollar free skin. Link in description."]
    for item in items:
        name = _spoken_name(item["name"])
        price = _money(item.get("price"), currency)
        lines.append(f"{name}, lowest listing {price}.")
    lines.append("Claim your ten dollar free skin. Link in description.")
    return lines


def _scene_timing(speech_durations: list[float]) -> tuple[list[float], float]:
    """Fit narration and readable promo cards inside the Shorts duration limit."""
    if len(speech_durations) < 3 or any(value <= 0 for value in speech_durations):
        raise ValueError("Aligned market narration needs positive promo, item, and outro durations")
    minimums = [2.8, *([2.6] * (len(speech_durations) - 2)), 3.2]
    pause = .28

    def durations_at(speed: float) -> list[float]:
        return [max(speech / speed + pause, minimum)
                for speech, minimum in zip(speech_durations, minimums)]

    speed = 1.0
    scene_durations = durations_at(speed)
    if sum(scene_durations) > 44.0:
        low, high = 1.0, 1.25
        while sum(durations_at(high)) > 44.0 and high < 4.0:
            high = min(4.0, high * 1.25)
        for _ in range(24):
            middle = (low + high) / 2
            if sum(durations_at(middle)) > 44.0:
                low = middle
            else:
                high = middle
        speed = high
        scene_durations = durations_at(speed)
    if sum(scene_durations) < 12:
        scene_durations[-1] += 12 - sum(scene_durations)
    return scene_durations, speed


def _synthesize_aligned_voiceover(ffmpeg: str, ffprobe: str, copy: VideoCopy,
                                  currency: str, data_dir: Path, voice: str
                                  ) -> tuple[Path, list[float]]:
    """Synthesize each visual beat separately, then pad it to its scene duration."""
    lines = _voiceover_lines(copy, currency)
    paths: list[Path] = []
    speech_durations: list[float] = []
    for index, line in enumerate(lines):
        part = data_dir / f"voice-part-{index + 1:02d}.mp3"
        synthesized = asyncio.run(_synthesize(line, voice, part))
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", str(synthesized)],
            check=True, capture_output=True, text=True,
        )
        speech_duration = float(result.stdout.strip())
        if speech_duration <= 0:
            raise RuntimeError(f"Speech synthesis generated empty audio for beat {index + 1}")
        paths.append(synthesized)
        speech_durations.append(speech_duration)

    # Promo cards stay readable; item cards stay up through their own spoken
    # name and price. Compress unusually slow TTS slightly, preserving pitch.
    scene_durations, speed = _scene_timing(speech_durations)
    if copy.series == "editorial" and speed > 1.15:
        raise RuntimeError("Editorial speech is too long for a natural-paced Short; publishing blocked")
    if speed > 1.0:
        log.warning("Skin-price narration exceeded 44 seconds at natural pace; applying %.2fx time compression", speed)
    duration = sum(scene_durations)

    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for path in paths:
        command.extend(["-i", str(path)])
    filters: list[str] = []
    for index, (speech_duration, scene_duration) in enumerate(zip(speech_durations, scene_durations)):
        pad = max(0.01, scene_duration - speech_duration / speed)
        filters.append(
            f"[{index}:a]atempo={speed:.5f},aresample=44100,apad=pad_dur={pad:.4f},"
            f"atrim=duration={scene_duration:.4f}[beat{index}]"
        )
    concat_inputs = "".join(f"[beat{index}]" for index in range(len(paths)))
    filters.append(f"{concat_inputs}concat=n={len(paths)}:v=0:a=1[voice]")
    voice_path = data_dir / "voice-aligned.wav"
    command.extend(["-filter_complex", ";".join(filters), "-map", "[voice]",
                    "-c:a", "pcm_s16le", "-ar", "44100", str(voice_path)])
    subprocess.run(command, check=True, capture_output=True, text=True)
    return voice_path, scene_durations


def render_video(copy: VideoCopy, currency: str, data_dir: Path, output_path: Path,
                 voice: str, image_fetch: bool = True, image_timeout: int = 8,
                 skinshotter_enabled: bool = False, skinshotter_clip_seconds: float = 5.0,
                 skinshotter_fallback_to_static: bool = False) -> float:
    ffmpeg, ffprobe = require_binary("ffmpeg"), require_binary("ffprobe")
    data_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    status_path = data_dir / "renderer-status.json"
    status_path.write_text(json.dumps({"renderer": "static catalog art"}, indent=2), encoding="utf-8")
    audio, scene_durations = _synthesize_aligned_voiceover(
        ffmpeg, ffprobe, copy, currency, data_dir, voice,
    )
    duration = sum(scene_durations)
    if skinshotter_enabled:
        # Keep capture inside the Actions job: no game server or manual recording.
        # Import lazily so local static renders and test environments do not need Chromium.
        from .skinshotter import SkinshotterRouteNotFoundError, capture_skin_clips

        try:
            catalog = _skin_catalog(data_dir, image_timeout)
            clips = capture_skin_clips((copy.items or [copy.featured])[:5], catalog,
                                       data_dir / "skinshotter", skinshotter_clip_seconds)
            final_duration = _render_pov_video(ffmpeg, ffprobe, copy, currency, data_dir, output_path,
                                               audio, duration, clips, scene_durations)
            status_path.write_text(json.dumps({
                "renderer": "Skinshotter POV", "clips": len(clips),
            }, indent=2), encoding="utf-8")
            return final_duration
        except SkinshotterRouteNotFoundError as exc:
            log.warning("Skinshotter has no page for a selected item; rendering the Short with catalog artwork: %s", exc)
            status_path.write_text(json.dumps({
                "renderer": "static catalog art (Skinshotter route missing)",
                "error": f"{type(exc).__name__}: {exc}",
            }, indent=2), encoding="utf-8")
        except Exception as exc:
            if not skinshotter_fallback_to_static:
                raise
            log.error("Skinshotter failed; using the existing static renderer to protect the scheduled upload: %s", exc)
            status_path.write_text(json.dumps({
                "renderer": "static catalog art (Skinshotter fallback)",
                "error": f"{type(exc).__name__}: {exc}",
            }, indent=2), encoding="utf-8")
    scenes = make_scenes(copy, currency, data_dir, image_fetch, image_timeout)
    if len(scenes) != len(scene_durations):
        raise RuntimeError("Narration beats and rendered scenes have different counts")
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for scene, scene_duration in zip(scenes, scene_durations):
        command.extend(["-loop", "1", "-framerate", "30", "-t", f"{scene_duration:.4f}", "-i", str(scene)])
    audio_input = len(scenes)
    command.extend(["-i", str(audio)])
    music_args, music_filter = _music_input(ffmpeg, duration, data_dir)
    music_input = audio_input + 1
    command.extend(music_args)
    filters: list[str] = []
    for index in range(len(scenes)):
        direction = "-" if index % 2 else "+"
        filters.append(
            f"[{index}:v]zoompan=z='min(zoom+0.00028,1.04)':"
            f"x='iw/2-(iw/zoom/2){direction}2*sin(on/28)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s=1080x1920:fps=30,trim=duration={scene_durations[index]:.4f},"
            f"setpts=PTS-STARTPTS,setsar=1[v{index}]"
        )
    concat_inputs = "".join(f"[v{i}]" for i in range(len(scenes)))
    filters.append(f"{concat_inputs}concat=n={len(scenes)}:v=1:a=0[vfinal]")
    filters.append(f"[{audio_input}:a]aresample=44100,apad=whole_dur={duration:.3f},"
                   f"loudnorm=I=-16:TP=-1.5:LRA=10[voice]")
    filters.append(f"[{music_input}:a]{music_filter}[bed]")
    # Split the narration: one copy is mixed at full level, the other gently
    # ducks the music while speech is present so words stay clear on phones.
    filters.append("[voice]asplit=2[voice_mix][voice_key]")
    filters.append("[bed][voice_key]sidechaincompress=threshold=0.025:ratio=7:attack=12:release=280:makeup=1[ducked_bed]")
    filters.append("[voice_mix][ducked_bed]amix=inputs=2:duration=first:weights='1 0.75':normalize=0,alimiter=limit=0.95[aout]")
    command.extend(["-filter_complex", ";".join(filters), "-map", "[vfinal]", "-map", "[aout]",
                    "-t", f"{duration:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(output_path)])
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
    final_duration = float(match.group(1)) if match else 0
    if final_duration < 12 or final_duration > 45:
        raise RuntimeError(f"Rendered Short duration outside 12–45 seconds: {final_duration:.2f}")
    return final_duration


