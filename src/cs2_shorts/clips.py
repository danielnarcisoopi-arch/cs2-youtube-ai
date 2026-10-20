"""Build and publish vertical Shorts from a single CS2 highlight clip."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw

from .config import settings
from .promotion import PROMO_MESSAGE, PROMO_URL, add_promo_link
from .scripts import VideoCopy
from .tactics import BG, MUTED, WHITE, _text, _wrap
from .youtube import upload_video

log = logging.getLogger(__name__)
WIDTH, HEIGHT = 1080, 1920
PROMO_SECONDS = 3.4
MAX_CLIP_SECONDS = 28.0
MIN_CLIP_SECONDS = 12.0 - 2 * PROMO_SECONDS
DATASET_API = "https://datasets-server.huggingface.co"
HUB_RESOLVE = "https://huggingface.co/datasets"
ACCENT = (77, 215, 234)


@dataclass(frozen=True)
class DatasetClip:
    path: str
    clip_id: str
    title: str
    steam_id: str
    fps: int


def _http_json(url: str, params: dict[str, Any], timeout: int = 40) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout,
                            headers={"User-Agent": "cs2-youtube-ai/1.0"})
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("Hugging Face returned an unexpected response")
    return result


def _dataset_split(dataset_id: str) -> tuple[str, str, int]:
    data = _http_json(f"{DATASET_API}/splits", {"dataset": dataset_id})
    splits = data.get("splits") or []
    candidates = [row for row in splits if row.get("config") == "metadata"] or splits
    split = next((row for row in candidates if row.get("split") == "metadata"), None)
    split = split or (candidates[0] if candidates else None)
    if not split:
        raise RuntimeError(f"No readable metadata split found for dataset {dataset_id}")
    count = int(split.get("num_examples") or 0)
    if count < 1:
        raise RuntimeError(f"Dataset metadata split has no rows: {dataset_id}")
    return str(split.get("config", "metadata")), str(split["split"]), count


def _candidate(row: dict[str, Any]) -> DatasetClip | None:
    value = row.get("file") or row.get("video") or row.get("path")
    if isinstance(value, dict):
        value = value.get("path") or value.get("name")
    if not isinstance(value, str):
        return None
    path = value.strip().replace("\\", "/").removeprefix("./")
    posix = PurePosixPath(path)
    if posix.is_absolute() or ".." in posix.parts or posix.suffix.lower() not in {".mp4", ".webm"}:
        return None
    # This project uses the videos collection, never previews or metadata files.
    if "videos" not in posix.parts:
        return None
    clip_id = posix.stem
    title = str(row.get("title") or "").strip()
    title = re.sub(r"\s+", " ", title)[:160]
    steam_id = str(row.get("steamid") or "").strip()
    fps_value = row.get("fps")
    try:
        fps = int(fps_value) if fps_value is not None else 0
    except (TypeError, ValueError):
        fps = 0
    return DatasetClip(path, clip_id, title, steam_id, fps)


def select_dataset_clip(dataset_id: str, recent: set[str],
                        rng: random.Random | Any = random) -> DatasetClip:
    """Pick a recent, unseen video row without downloading the full dataset."""
    config, split, count = _dataset_split(dataset_id)
    length = min(100, count)
    for _ in range(24):
        offset = rng.randrange(count)
        # Hugging Face's rows API returns up to 100 rows per request.
        offset = (offset // length) * length
        data = _http_json(f"{DATASET_API}/rows", {
            "dataset": dataset_id, "config": config, "split": split,
            "offset": offset, "length": length,
        })
        rows = data.get("rows") or []
        candidates = []
        for wrapped in rows:
            row = wrapped.get("row", wrapped) if isinstance(wrapped, dict) else {}
            candidate = _candidate(row) if isinstance(row, dict) else None
            if candidate and candidate.path not in recent:
                candidates.append(candidate)
        if candidates:
            return rng.choice(candidates)
    raise RuntimeError("Could not find an unseen MP4/WebM clip in the dataset after 24 samples")


def download_dataset_clip(dataset_id: str, clip: DatasetClip, destination: Path,
                          max_bytes: int = 220 * 1024 * 1024) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded_path = quote(clip.path, safe="/")
    url = f"{HUB_RESOLVE}/{dataset_id}/resolve/main/{encoded_path}?download=true"
    temporary = destination.with_suffix(destination.suffix + ".part")
    total = 0
    try:
        with requests.get(url, stream=True, timeout=(20, 120), allow_redirects=True,
                          headers={"User-Agent": "cs2-youtube-ai/1.0"}) as response:
            response.raise_for_status()
            declared_size = response.headers.get("Content-Length")
            if declared_size and int(declared_size) > max_bytes:
                raise RuntimeError(f"Dataset clip is too large ({int(declared_size)} bytes); limit is {max_bytes}")
            with temporary.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError(f"Dataset clip exceeded the {max_bytes}-byte download limit")
                    output.write(chunk)
        if total < 4096:
            raise RuntimeError("Downloaded dataset clip is empty or incomplete")
        temporary.replace(destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_clip_copy(clip: DatasetClip, dataset_id: str) -> VideoCopy:
    raw_title = clip.title or f"Community clip {clip.clip_id}"
    clean_title = re.sub(r"[\r\n]+", " ", raw_title).strip()
    title = ("CS2 Highlight: " + clean_title)[:100]
    source_line = f"Source clip: {dataset_id} / {clip.path}"
    if clip.steam_id:
        source_line += f"\nOriginal uploader Steam ID: {clip.steam_id}"
    description = add_promo_link(
        f"CS2 gameplay highlight.\n\n{source_line}\n"
        f"Dataset: https://huggingface.co/datasets/{dataset_id}\n\n"
        "#CS2 #CounterStrike2 #CS2Highlights #Gaming"
    )
    return VideoCopy(title, description,
                     ["CS2", "Counter-Strike 2", "CS2 highlights", "gaming"],
                     "A Counter-Strike two highlight. Watch the play.",
                     "community_clip", {"name": clean_title})


def _draw_promo_card(phase: str) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    top = (7, 15, 25)
    bottom = (10, 31, 43)
    gradient = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        color = tuple(round(top[c] * (1 - ratio) + bottom[c] * ratio) for c in range(3))
        gradient.line((0, y, WIDTH, y), fill=color)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64, 76, 1016, 154), radius=24,
                           fill=(17, 31, 43), outline=(46, 70, 84), width=2)
    _text(draw, "CS2  /  COMMUNITY HIGHLIGHTS", (540, 115), 25, WHITE, True, anchor="mm")
    draw.rounded_rectangle((48, 430, 1032, 1195), radius=42,
                           fill=(5, 9, 15), outline=ACCENT, width=7)
    promo_title, promo_cta = PROMO_MESSAGE.split(", ", 1)
    _text(draw, promo_title + ",", (540, 630), 76, ACCENT, True, anchor="mm")
    _text(draw, promo_cta, (540, 755), 49, WHITE, True, anchor="mm")
    draw.rounded_rectangle((142, 875, 938, 975), radius=26,
                           fill=(24, 35, 28), outline=ACCENT, width=3)
    _text(draw, PROMO_URL.removeprefix("http://"), (540, 925), 36, ACCENT, True, anchor="mm")
    label = "START HERE" if phase == "intro" else "CLAIM YOUR FREE SKIN"
    _text(draw, label, (540, 1080), 24, MUTED, True, anchor="mm")
    _text(draw, "LINK IN DESCRIPTION", (540, 1325), 27, WHITE, True, anchor="mm")
    return image


def _draw_clip_overlay() -> Image.Image:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((50, 70, 850, 158), radius=22,
                           fill=(5, 9, 15, 205), outline=(*ACCENT, 230), width=2)
    _text(draw, "CS2 COMMUNITY HIGHLIGHT", (82, 114), 26, WHITE, True, anchor="lm")
    draw.rounded_rectangle((140, 1700, 940, 1780), radius=22, fill=(5, 9, 15, 190))
    _text(draw, "WATCH THE PLAY  ·  CS2", (540, 1740), 23, WHITE, True, anchor="mm")
    return overlay


def _probe_video(ffprobe: str, path: Path) -> tuple[float, bool]:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(path)], check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    has_audio = any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))
    if not math.isfinite(duration) or duration < MIN_CLIP_SECONDS:
        raise RuntimeError(f"Dataset clip is too short for the promo intro and outro: {duration:.2f}s")
    return min(duration, MAX_CLIP_SECONDS), has_audio


def render_clip(clip_path: Path, copy: VideoCopy, output_path: Path,
                render_dir: Path, voice: str) -> float:
    from .media import _synthesize, require_binary

    ffmpeg, ffprobe = require_binary("ffmpeg"), require_binary("ffprobe")
    clip_duration, has_audio = _probe_video(ffprobe, clip_path)
    render_dir.mkdir(parents=True, exist_ok=True)
    promo_voice_path = asyncio.run(_synthesize(
        "Ten dollar free skin. Link in description.", voice,
        render_dir / "promo-voice.mp3",
    ))
    intro_path = render_dir / "promo-intro.png"
    outro_path = render_dir / "promo-outro.png"
    overlay_path = render_dir / "clip-overlay.png"
    render_dir.mkdir(parents=True, exist_ok=True)
    _draw_promo_card("intro").save(intro_path, optimize=True)
    _draw_promo_card("outro").save(outro_path, optimize=True)
    _draw_clip_overlay().save(overlay_path, optimize=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = clip_duration + 2 * PROMO_SECONDS
    silence_duration = clip_duration if not has_audio else 0.1
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-loop", "1", "-framerate", "30", "-t", f"{PROMO_SECONDS:.3f}", "-i", str(intro_path),
               "-i", str(clip_path),
               "-loop", "1", "-framerate", "30", "-t", f"{PROMO_SECONDS:.3f}", "-i", str(outro_path),
               "-i", str(promo_voice_path),
               "-f", "lavfi", "-t", f"{silence_duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-loop", "1", "-framerate", "30", "-t", f"{clip_duration:.3f}", "-i", str(overlay_path),
               "-i", str(promo_voice_path),
               "-f", "lavfi", "-t", f"{PROMO_SECONDS:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    clip_audio = "1:a" if has_audio else "4:a"
    filters = [
        "[0:v]fps=30,scale=1080:1920,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[intro_v]",
        "[1:v]split=2[bg0][fg0]",
        "[bg0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:10,eq=brightness=-0.25,setsar=1[bg]",
        "[fg0]scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2:color=black@0,format=rgba[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1[base]",
        f"[base][5:v]overlay=0:0:shortest=1,fps=30,trim=duration={clip_duration:.3f},setpts=PTS-STARTPTS,format=yuv420p[clip_v]",
        "[2:v]fps=30,scale=1080:1920,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[outro_v]",
        f"[3:a]aresample=44100,aformat=channel_layouts=stereo,apad,atrim=duration={PROMO_SECONDS:.3f},asetpts=PTS-STARTPTS[intro_a]",
        f"[{clip_audio}]aresample=44100,aformat=channel_layouts=stereo,apad,atrim=duration={clip_duration:.3f},asetpts=PTS-STARTPTS[clip_a]",
        f"[6:a]aresample=44100,aformat=channel_layouts=stereo,apad,atrim=duration={PROMO_SECONDS:.3f},asetpts=PTS-STARTPTS[outro_a]",
        "[intro_v][intro_a][clip_v][clip_a][outro_v][outro_a]concat=n=3:v=1:a=1[outv][prea]",
        "[prea]alimiter=limit=0.95[outa]",
    ]
    command.extend(["-filter_complex", ";".join(filters), "-map", "[outv]", "-map", "[outa]",
                    "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(output_path)])
    subprocess.run(command, check=True, capture_output=True, text=True)
    verify = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=width,height",
                             "-of", "json", str(output_path)], check=True, capture_output=True, text=True)
    data = json.loads(verify.stdout)
    stream = data["streams"][0]
    rendered_duration = float(data["format"]["duration"])
    if (stream.get("width"), stream.get("height")) != (WIDTH, HEIGHT):
        raise RuntimeError(f"Rendered clip has invalid dimensions: {stream.get('width')}x{stream.get('height')}")
    if not 12 <= rendered_duration <= 45:
        raise RuntimeError(f"Rendered clip length is outside Shorts limits: {rendered_duration:.2f}s")
    return rendered_duration


def _history(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(value) for value in data.get("published", [])]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def _record_clip(path: Path, clip: DatasetClip) -> None:
    used = _history(path)
    if clip.path not in used:
        used.append(clip.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"published": used[-2000:]}, indent=2), encoding="utf-8")
    temporary.replace(path)


def run() -> Path:
    from .media import require_binary

    cfg = settings
    dataset_id = os.getenv("CS2_CLIPS_DATASET_ID", "nyuuzyou/cs2-highlights").strip()
    max_bytes = int(os.getenv("CS2_CLIP_MAX_BYTES", str(220 * 1024 * 1024)))
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    history_path = cfg.data_dir / "clips-history.json"
    render_dir = cfg.data_dir / "render" / "clips"
    recent = set(_history(history_path))
    ffprobe = require_binary("ffprobe")
    clip = None
    source_path = None
    for _ in range(5):
        candidate = select_dataset_clip(dataset_id, recent)
        candidate_path = render_dir / f"{candidate.clip_id}{PurePosixPath(candidate.path).suffix.lower()}"
        try:
            download_dataset_clip(dataset_id, candidate, candidate_path, max_bytes=max_bytes)
            try:
                _probe_video(ffprobe, candidate_path)
            except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
                candidate_path.unlink(missing_ok=True)
                log.warning("Skipping unusable dataset clip %s: %s", candidate.path, exc)
                recent.add(candidate.path)
                continue
            clip, source_path = candidate, candidate_path
            break
        except RuntimeError as exc:
            if not any(token in str(exc) for token in ("too large", "exceeded the", "empty or incomplete")):
                raise
            log.warning("Skipping oversized dataset clip %s: %s", candidate.path, exc)
            recent.add(candidate.path)
    if clip is None or source_path is None:
        raise RuntimeError("No dataset clip under the configured download-size limit was found")
    copy = build_clip_copy(clip, dataset_id)
    now = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Lisbon"))
    run_id = os.getenv("GITHUB_RUN_ID") or f"{now:%H%M%S}-{random.randrange(1000, 9999)}"
    stamp = f"{now:%Y%m%d-%H%M}-{run_id}"
    output_path = cfg.output_dir / f"{stamp}-cs2-clip-{clip.clip_id}.mp4"
    duration = render_clip(source_path, copy, output_path, render_dir, cfg.voice)
    metadata = {
        "series": "CS2 Community Highlights", "dataset": dataset_id, "source_clip": clip.path,
        "source_title": clip.title, "source_steam_id": clip.steam_id, "source_fps": clip.fps,
        "title": copy.title, "duration_seconds": round(duration, 2),
        "video_file": str(output_path), "upload_enabled": cfg.upload_enabled,
    }
    metadata_path = output_path.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    log.info("Rendered CS2 community clip: %s (%.1f seconds)", output_path, duration)
    if cfg.upload_enabled:
        video_id = upload_video(output_path, copy, cfg)
        metadata["youtube_video_id"] = video_id
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        log.info("Published CS2 clip: https://youtube.com/shorts/%s", video_id)
    _record_clip(history_path, clip)
    return output_path


def main() -> None:
    logging.basicConfig(level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()


if __name__ == "__main__":
    main()
