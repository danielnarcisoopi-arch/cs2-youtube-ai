"""Automated, clearly labelled 5v5 tactical play simulations for CS2 Shorts.

This series is intentionally separate from ``tactics.py`` / Round IQ. It uses
real CS2 radar artwork and published callout anchors, but its player movement is
an illustrative route animation, not captured demo data or a navmesh-validated
recreation of a match.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageOps

from .tactics import (
    BG, GOLD, H, MUTED, W, WHITE, _background, _load_callouts, _load_radar,
    _resolve_callout, _text, _wrap,
)
from .promotion import PROMO_MESSAGE, add_promo_link

log = logging.getLogger(__name__)
FPS = 6
SIM_SECONDS = 17.0
ATTACK = (77, 215, 234)
DEFEND = (255, 116, 98)


@dataclass(frozen=True)
class PlayScenario:
    key: str
    title: str
    hook: str
    map_id: str
    map_name: str
    attackers_start: str
    bombsite: str
    side: str
    narration: str
    event: str


# The endpoints are existing named callouts already used by the Round IQ map
# contexts. Each episode builds a distinct site hit from these published points.
PLAYS: tuple[PlayScenario, ...] = (
    PlayScenario("mirage-a-execute", "The Mirage A execute", "Can five players hit A before the defense resets?",
                 "de_mirage", "MIRAGE", "A Ramp", "A Site", "A",
                 "Watch the timing here. Five attackers group before the A hit, and the first flash lands just as the entry reaches the site. The defenders have to choose: hold their angles or give up space for the retake. The key is the spacing behind the first player. If the second player arrives late, that flash wins nothing. Would you send the first player or the trade player through the smoke?", "FLASH POP  ·  A ENTRY"),
    PlayScenario("inferno-b-execute", "The Inferno B hit", "Can the B defense survive a timed Banana hit?",
                 "de_inferno", "INFERNO", "Banana", "B Site", "B",
                 "Five attackers are moving together toward B. The flash goes over before the first player commits, giving the entry a short window to clear the close angle. The defenders start to rotate as contact is made, while one stays alive to delay the plant. Watch how the second attacker follows close enough to trade. Would you fight for Banana or save utility for the retake?", "FLASH POP  ·  B ENTRY"),
    PlayScenario("dust2-a-execute", "The Dust II A hit", "The first player is seen. Does the trade arrive in time?",
                 "de_dust2", "DUST II", "Long A", "A Site", "A",
                 "The attackers take Long A as a group, with the entry and trade player almost shoulder to shoulder. A flash pops over the site before they cross into the open. Two defenders hold the site while the others begin to rotate. The point is not to run in together blindly: clear the close angle, then let the next player take the trade. Who should take first contact?", "FLASH POP  ·  LONG A HIT"),
    PlayScenario("ancient-b-execute", "The Ancient B execute", "Can the B defense survive a timed hit through mid?",
                 "de_ancient", "ANCIENT", "Middle", "B Site", "B",
                 "Five attackers are grouping through mid toward B. One flash breaks the held angle, then the first pair clears together while the next players cover the trade and flank. Notice the pause before the final swing: entering one by one would give the defenders five separate duels. Would you flash first or smoke the plant?", "FLASH POP  ·  B EXECUTE"),
    PlayScenario("anubis-b-execute", "The Anubis B split", "Can the split arrive together, or does it become three solo fights?",
                 "de_anubis", "ANUBIS", "B Main", "B Site", "B",
                 "The B hit only works if the group reaches the site on one timing. The lead pair draws attention, the flash creates the opening, and the last players stay close enough to trade instead of chasing separate fights. The defenders start to collapse onto the site, so the attackers need to secure space and plant. Would you commit now or wait for the late player?", "FLASH POP  ·  B SPLIT"),
)


@dataclass(frozen=True)
class PlayCopy:
    title: str
    description: str
    tags: list[str]
    narration: str


def build_play_copy(play: PlayScenario) -> PlayCopy:
    description = add_promo_link(
        f"Illustrative 5v5 CS2 tactical simulation on the {play.map_name} radar. "
        "Player routes and utility are animated for teaching; this is not captured demo footage, "
        "a verified pro play, or an exact grenade lineup. Use it as a discussion prompt.\n\n"
        "Map radar artwork © Valve Corporation; sourced from MurkyYT/cs2-map-icons.\n\n"
        "#CS2 #CounterStrike2 #CS2Tactics #CS2Plays"
    )
    return PlayCopy(f"CS2 Playbook: {play.title}"[:100], description,
                    ["CS2", "Counter-Strike 2", "CS2 tactics", "CS2 playbook"], play.narration)


def _map_geometry(radar: Image.Image) -> tuple[Image.Image, tuple[int, int], tuple[int, int]]:
    map_box = (92, 448, 988, 1320)
    fitted = ImageOps.contain(radar.convert("RGB"), (map_box[2] - map_box[0], map_box[3] - map_box[1]))
    origin = (map_box[0] + (map_box[2] - map_box[0] - fitted.width) // 2,
              map_box[1] + (map_box[3] - map_box[1] - fitted.height) // 2)
    return fitted, origin, (fitted.width, fitted.height)


def _nearest_callouts(points: dict[str, tuple[float, float]], center: tuple[float, float], count: int) -> list[tuple[str, tuple[float, float]]]:
    """Pick radar callout anchors near the site for a readable CT setup."""
    center_name = min(points, key=lambda key: math.dist(points[key], center))
    ordered = sorted(points.items(), key=lambda item: math.dist(item[1], center))
    # Keep a minimum separation so five defenders remain individually visible.
    selected: list[tuple[str, tuple[float, float]]] = []
    for item in ordered:
        if all(math.dist(item[1], old[1]) > 0.060 for old in selected):
            selected.append(item)
        if len(selected) >= count:
            break
    if not selected:
        selected = [(center_name, center)]
    return selected


def _route_point(start: tuple[float, float], end: tuple[float, float], t: float,
                 lane: float) -> tuple[float, float]:
    """Interpolate a lane-spaced illustrative approach between map callouts."""
    t = min(1.0, max(0.0, t))
    # Offset along the perpendicular keeps the five attackers legible.
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max(math.hypot(dx, dy), 1e-5)
    offset = lane * 0.026
    bend = math.sin(t * math.pi) * 0.018
    x = start[0] + dx * t - dy / length * (offset + bend)
    y = start[1] + dy * t + dx / length * (offset + bend)
    return min(0.965, max(0.035, x)), min(0.965, max(0.035, y))


def _draw_play_frame(play: PlayScenario, episode: int, frame: int,
                     radar: Image.Image, callouts: dict[str, tuple[float, float]],
                     duration: float = SIM_SECONDS) -> Image.Image:
    elapsed = frame / FPS
    image = _background()
    draw = ImageDraw.Draw(image)
    flash_at = duration * 0.48
    plant_at = duration * 0.76
    progress = min(1.0, max(0.0, (elapsed - 2.0) / max(1.0, duration - 2.0)))
    start = _resolve_callout(callouts, play.attackers_start)
    site = _resolve_callout(callouts, play.bombsite)
    fitted, origin, dimensions = _map_geometry(radar)
    image.paste(fitted, origin)

    # Header and concise five-versus-five scoreboard.
    draw.rounded_rectangle((64, 62, 1016, 146), 22, fill=(17, 31, 43), outline=(46, 70, 84), width=2)
    _text(draw, "CS2  /  PLAYBOOK", (92, 104), 22, WHITE, True, anchor="lm")
    _text(draw, f"SIM {episode:02d}", (985, 104), 18, MUTED, True, anchor="rm")
    hook = play.hook if elapsed < 3.4 else play.title
    for i, line in enumerate(_wrap(hook, 31)):
        _text(draw, line, (66, 190 + i * 59), 46 if len(_wrap(hook, 31)) <= 2 else 39, WHITE, True)

    if elapsed < 3.4:
        draw.rounded_rectangle((94, 320, 986, 370), 18, fill=(8, 18, 27), outline=ATTACK, width=2)
        _text(draw, PROMO_MESSAGE, (540, 345), 22, ATTACK, True, anchor="mm")

    draw.rounded_rectangle((64, 370, 1016, 430), 18, fill=(14, 26, 37), outline=(49, 69, 82), width=2)
    _text(draw, f"{play.map_name}  ·  {play.side} SITE EXECUTE", (88, 400), 19, WHITE, True, anchor="lm")
    _text(draw, "5  ATTACK" if progress < .1 else "5  ATTACK  ·  ENTRY", (991, 400), 17, ATTACK, True, anchor="rm")
    _text(draw, "5v5  ·  ILLUSTRATIVE SIMULATION", (540, 1374), 18, MUTED, True, anchor="mm")

    def screen(point: tuple[float, float]) -> tuple[float, float]:
        x = min(0.965, max(0.035, point[0]))
        y = min(0.965, max(0.035, point[1]))
        return origin[0] + x * dimensions[0], origin[1] + y * dimensions[1]

    # Entry lanes are rendered as a subtle dashed trail; the points remain the focus.
    steps = 18
    for j in range(0, steps, 2):
        t0, t1 = progress * j / steps, progress * (j + 1) / steps
        p0 = screen(_route_point(start, site, t0, 0.0))
        p1 = screen(_route_point(start, site, t1, 0.0))
        draw.line((*p0, *p1), fill=(48, 131, 151), width=3)

    # Five attacker markers stagger their entry to teach spacing and trading.
    for player in range(5):
        player_progress = min(1.0, max(0.0, progress * 1.12 - player * 0.17))
        p = screen(_route_point(start, site, player_progress, player - 2))
        x, y = p
        r = 21
        draw.ellipse((x-r-4, y-r-4, x+r+4, y+r+4), fill=(10, 20, 29), outline=ATTACK, width=4)
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(17, 81, 96))
        _text(draw, f"T{player+1}", (x, y), 15, WHITE, True, anchor="mm")
        if player == 4:
            draw.ellipse((x+12, y+12, x+30, y+30), fill=GOLD, outline=(12, 21, 29), width=2)
            _text(draw, "B", (x+21, y+21), 11, BG, True, anchor="mm")

    # Five defenders occupy five distinct nearby named radar callouts.
    defensive = _nearest_callouts(callouts, site, 5)
    for player, (name, pos) in enumerate(defensive):
        x, y = screen(pos)
        # One CT rotates toward the site after the attack is spotted.
        if player == 0 and elapsed > duration * 0.32:
            source = pos
            rotate = min(1.0, (elapsed - duration * 0.32) / max(1.0, duration * 0.32))
            pos = (source[0] + (site[0] - source[0]) * rotate,
                   source[1] + (site[1] - source[1]) * rotate)
            x, y = screen(pos)
        r = 19
        draw.ellipse((x-r-4, y-r-4, x+r+4, y+r+4), fill=(10, 20, 29), outline=DEFEND, width=4)
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(104, 44, 43))
        _text(draw, f"C{player+1}", (x, y), 14, WHITE, True, anchor="mm")

    # Flash pop immediately before entry; the icon/rings fade over a short beat.
    if abs(elapsed - flash_at) < 1.7:
        x, y = screen(site)
        strength = max(0.0, 1.0 - abs(elapsed - flash_at) / 1.7)
        radius = 35 + int((1.0 - strength) * 95)
        color = (int(90 + 150 * strength), int(190 + 60 * strength), int(220 + 35 * strength))
        for ring in range(3):
            rr = radius + ring * 25
            draw.ellipse((x-rr, y-rr, x+rr, y+rr), outline=color, width=4)
        label_x = min(max(68, int(x - 120)), 770)
        label_y = min(max(origin[1] + 8, int(y - 66)), origin[1] + dimensions[1] - 54)
        draw.rounded_rectangle((label_x, label_y, label_x+242, label_y+46), 12,
                               fill=(11, 22, 31), outline=ATTACK, width=2)
        _text(draw, "FLASH POP", (label_x+121, label_y+23), 16, WHITE, True, anchor="mm")

    # Site and bomb marker.
    sx, sy = screen(site)
    site_tag_x = min(max(origin[0] + 4, int(sx - 44)), origin[0] + dimensions[0] - 94)
    site_tag_y = min(max(origin[1] + 4, int(sy + 22)), origin[1] + dimensions[1] - 48)
    draw.rounded_rectangle((site_tag_x, site_tag_y, site_tag_x+90, site_tag_y+40), 11,
                           fill=(17, 32, 43), outline=GOLD, width=2)
    _text(draw, f"{play.side} SITE", (site_tag_x+45, site_tag_y+20), 13, GOLD, True, anchor="mm")
    if elapsed > plant_at:
        draw.rounded_rectangle((sx-20, sy-70, sx+20, sy-30), 10,
                               fill=(32, 29, 19), outline=GOLD, width=2)
        _text(draw, "C4", (sx, sy-50), 14, GOLD, True, anchor="mm")

    beat = ("GROUP UP" if elapsed < 2 else "FLASH THE ENTRY" if elapsed < flash_at
            else "TAKE SPACE" if elapsed < plant_at else "PLANT  ·  SET THE CROSSFIRE")
    draw.rounded_rectangle((64, 1452, 1016, 1600), 24, fill=(15, 29, 41), outline=(47, 72, 87), width=2)
    _text(draw, beat, (90, 1494), 25, ATTACK if elapsed < flash_at else GOLD, True)
    _text(draw, play.event, (90, 1546), 18, WHITE, True)
    # Timeline dots move throughout the map play, not only at scene cuts.
    draw.rounded_rectangle((66, 1684, 1014, 1694), 5, fill=(40, 55, 67))
    draw.rounded_rectangle((66, 1684, 66 + int(948 * elapsed / duration), 1694), 5, fill=ATTACK)
    _text(draw, "T  ATTACKERS", (68, 1746), 17, ATTACK, True)
    _text(draw, "CT  DEFENDERS", (1012, 1746), 17, DEFEND, True, anchor="ra")
    _text(draw, "ILLUSTRATIVE SIMULATION  ·  NOT DEMO FOOTAGE", (540, 1834), 16, MUTED, True, anchor="mm")
    return image


def _history(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(key) for key in data.get("published", [])]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def choose_play(history_path: Path) -> tuple[PlayScenario, int]:
    used = _history(history_path)
    remaining = [play for play in PLAYS if play.key not in used]
    if not remaining:
        remaining = list(PLAYS)
    selected = remaining[0]
    return selected, PLAYS.index(selected) + 1


def _record_play(path: Path, play: PlayScenario) -> None:
    used = _history(path)
    if play.key not in used:
        used.append(play.key)
    if len(used) >= len(PLAYS):
        used = []
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"published": used}, indent=2), encoding="utf-8")
    temporary.replace(path)


def render_play(play: PlayScenario, episode: int, output_path: Path,
                data_dir: Path, voice: str):
    from .media import _music_input, _synthesize, require_binary

    ffmpeg, ffprobe = require_binary("ffmpeg"), require_binary("ffprobe")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    copy = build_play_copy(play)
    audio = asyncio.run(_synthesize(copy.narration, voice, data_dir / "play-voice.mp3"))
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", str(audio)],
                           check=True, capture_output=True, text=True)
    speech_duration = float(probe.stdout.strip())
    if not 12 <= speech_duration <= 38:
        raise RuntimeError(f"Play narration must be 12–38 seconds, got {speech_duration:.2f}s")

    radar = _load_radar(play.map_id)
    callouts = _load_callouts(play.map_id)
    total = max(SIM_SECONDS, speech_duration + 0.8)
    frame_count = math.ceil(total * FPS)
    total = frame_count / FPS
    # Generate actual animation frames so players move continuously at 6 fps.
    frame_dir = data_dir / f"play-{play.key}"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for stale in frame_dir.glob("frame-*.jpg"):
        stale.unlink()
    for frame in range(frame_count):
        _draw_play_frame(play, episode, frame, radar, callouts, total).save(
            frame_dir / f"frame-{frame:04d}.jpg", quality=88, optimize=True)

    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-framerate", str(FPS), "-i", str(frame_dir / "frame-%04d.jpg"),
               "-i", str(audio)]
    music_args, music_filter = _music_input(ffmpeg, total, data_dir)
    music_input = 2
    command.extend(music_args)
    filters = [f"[0:v]fps=30,scale={W}:{H},trim=duration={total:.3f},setpts=PTS-STARTPTS,setsar=1[vfinal]",
               f"[1:a]aresample=44100,apad=whole_dur={total:.3f},loudnorm=I=-16:TP=-1.5:LRA=10[voice]",
               f"[{music_input}:a]{music_filter}[bed]", "[voice]asplit=2[voice_mix][voice_key]",
               "[bed][voice_key]sidechaincompress=threshold=0.025:ratio=7:attack=12:release=280:makeup=1[ducked_bed]",
               "[voice_mix][ducked_bed]amix=inputs=2:duration=first:weights='1 0.60':normalize=0,alimiter=limit=0.95[aout]"]
    command.extend(["-filter_complex", ";".join(filters), "-map", "[vfinal]", "-map", "[aout]",
                    "-t", f"{total:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(output_path)])
    subprocess.run(command, check=True, capture_output=True, text=True)
    verified = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=width,height",
                               "-of", "json", str(output_path)], check=True, capture_output=True, text=True)
    result = json.loads(verified.stdout)
    stream = result["streams"][0]
    duration = float(result["format"]["duration"])
    if (stream.get("width"), stream.get("height")) != (W, H) or not 12 <= duration <= 45:
        raise RuntimeError(f"Rendered play has invalid output: {stream.get('width')}x{stream.get('height')} / {duration:.2f}s")
    return duration, copy


def run() -> Path:
    from .config import settings
    from .youtube import upload_video

    cfg = settings
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    history_path = cfg.data_dir / "plays-history.json"
    play, episode = choose_play(history_path)
    now = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Lisbon"))
    run_id = os.getenv("GITHUB_RUN_ID") or now.strftime("%H%M%S")
    stamp = f"{now.strftime('%Y%m%d-%H%M')}-{run_id}"
    video_path = cfg.output_dir / f"{stamp}-cs2-play-{play.key}.mp4"
    duration, copy = render_play(play, episode, video_path, cfg.data_dir / "render" / "plays", cfg.voice)
    metadata = {"series": "CS2 Playbook", "scenario_key": play.key, "episode": episode,
                "title": copy.title, "narration": copy.narration, "duration_seconds": round(duration, 2),
                "video_file": str(video_path), "upload_enabled": cfg.upload_enabled,
                "map": play.map_name, "site": play.side,
                "visuals": "animated 5v5 illustrative simulation on CS2 radar; not demo-derived"}
    metadata_path = video_path.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    log.info("Rendered CS2 Playbook: %s (%.1f seconds)", video_path, duration)
    if cfg.upload_enabled:
        video_id = upload_video(video_path, copy, cfg)
        metadata["youtube_video_id"] = video_id
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        _record_play(history_path, play)
        log.info("Published CS2 Playbook: https://youtube.com/shorts/%s", video_id)
    return video_path


def main() -> None:
    from .config import settings
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()


if __name__ == "__main__":
    main()
