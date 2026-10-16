from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageOps

log = logging.getLogger(__name__)
W, H = 1080, 1920
BG = (8, 14, 23)
PANEL = (16, 28, 41)
GRID = (35, 55, 68)
CYAN = (85, 226, 226)
CORAL = (255, 125, 93)
GOLD = (246, 205, 101)
WHITE = (244, 247, 249)
MUTED = (155, 176, 189)


def _font(size: int, bold: bool = False):
    path = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _text(draw: ImageDraw.ImageDraw, value: str, xy: tuple[int, int], size: int,
          color: tuple[int, int, int] = WHITE, bold: bool = False,
          anchor: str | None = None) -> None:
    draw.text(xy, value, font=_font(size, bold), fill=color, anchor=anchor)


@dataclass(frozen=True)
class Tactic:
    key: str
    title: str
    hook: str
    setup: str
    action: str
    payoff: str
    question: str
    lane: int

    @property
    def narration(self) -> str:
        return " ".join((self.hook, self.setup, self.action, self.payoff, self.question))


# These are general competitive fundamentals. Map context and teaching routes are
# attached below; none of the episodes claims to reproduce a specific demo.
TACTICS: tuple[Tactic, ...] = (
    Tactic("trade-spacing", "Trade spacing", "Your teammate gets picked. Can you trade it?",
           "If you are too far back, the duel is already over.",
           "Stay close enough to swing as the shot lands, then clear the same threat together.",
           "One player takes contact; the second converts it into a trade.",
           "Do you play close enough to trade?", 0),
    Tactic("two-v-one", "Turn a 2v1 into a crossfire", "In a 2v1, stop taking turns peeking.",
           "The defender only needs to win one clean duel at a time.",
           "Hold two different lines and swing on the same cue.",
           "Now one opponent has to clear both angles before the clock runs out.",
           "Would you hold or swing first?", 1),
    Tactic("anti-eco", "Respect the close range", "Against a low-buy, the close corner is the danger.",
           "A cheap weapon can still win a point-blank fight.",
           "Move as a pair, clear the nearest space, then take the long angle.",
           "You deny the isolated close duel the weaker buy needs.",
           "Do you clear close first?", 2),
    Tactic("flash-entry", "Flash for your teammate", "A flash is strongest when a teammate can use it.",
           "Throwing it after the entry has already stopped wastes the timing.",
           "Call the flash, turn away, then swing together as it pops.",
           "The utility creates the opening; the synchronized peek takes it.",
           "Do you call before you throw?", 3),
    Tactic("post-plant", "Stop re-peeking after plant", "The bomb is down. You do not need another duel.",
           "A solo peek gives the retake a free first fight.",
           "Fall into a crossfire, keep one player watching the defuse route, and trade contact.",
           "Make the retake clear two threats before it can touch the bomb.",
           "Would you hold the angle or chase?", 4),
    Tactic("late-round", "Group before the final hit", "Three players alive, but arriving one by one?",
           "Staggered entries give the defense three separate duels.",
           "Pause, share the last utility, and hit the space on one call.",
           "A grouped execute forces the defense to manage several threats at once.",
           "Do you reset or keep trickling in?", 0),
    Tactic("rotate-info", "Rotate on useful information", "One sound cue is not always a full commitment.",
           "A rushed rotation can leave the other site undefended.",
           "Have one player verify while the rest shift to safer positions.",
           "You protect the site and still keep the option to rotate together.",
           "Would you rotate on one sound?", 1),
    Tactic("reposition", "Reposition after the first kill", "You got the opening pick. They know your angle now.",
           "Holding the same line invites an instant trade.",
           "Fall back behind cover and make the next peek come from a new spot.",
           "The first kill gains space; the reposition keeps the advantage alive.",
           "Do you move after the pick?", 2),
    Tactic("deny-isolation", "Do not split your entry", "Two routes can still mean two isolated fights.",
           "If neither player can trade, the defense can take each duel safely.",
           "Use one route to draw attention while the second stays close enough to support.",
           "The goal is pressure with a trade, not distance for its own sake.",
           "Can your second player trade that route?", 3),
    Tactic("retake-utility", "Use utility before the retake", "Retaking through a held angle with no flash is a gift.",
           "The defender can take the first fight and fall back.",
           "Use a flash or smoke to break the angle, then clear together.",
           "Utility buys the space your team needs to start the retake.",
           "Would you spend the flash here?", 4),
    Tactic("protect-utility", "Keep one option for later", "Using every grenade on the first sighting can cost the round.",
           "The opponent may still have a second hit or a retake.",
           "Spend what wins space now, but keep a useful piece for the next phase.",
           "A planned reserve gives your team another answer when the round changes.",
           "What would you save for the retake?", 0),
    Tactic("trade-not-chase", "Trade the fight, not the kill", "Your teammate sees contact. Do not chase past them.",
           "Overrunning the angle can expose you to a second defender.",
           "Hold the trade distance, clear the next threat, then take the space together.",
           "You convert the first contact without donating another isolated duel.",
           "Would you chase or secure the trade?", 1),
    Tactic("sound-discipline", "Use sound without giving yours away", "You heard a rotation. Do not sprint into its path.",
           "Your own footsteps can reveal the position you meant to exploit.",
           "Slow down near the contact area and let the sound guide a safer move.",
           "Information is useful when your next action does not erase your advantage.",
           "Would you walk or run here?", 2),
    Tactic("crossfire", "Make the opponent clear two angles", "Two defenders on one line are easy to blind together.",
           "A single flash can remove both players from the fight.",
           "Separate the angles while staying close enough to trade.",
           "Now the attacker must expose themselves to one defender to fight the other.",
           "Would you stack or split the angle?", 3),
    Tactic("hold-discipline", "Do not abandon a strong angle early", "You have the angle. The urge to peek again is the trap.",
           "A second peek gives the opponent a timing they can prepare for.",
           "Hold, let your teammate gather info, and move only when the round calls for it.",
           "Discipline keeps the defense unpredictable.",
           "Would you re-peek for the highlight?", 4),
    Tactic("focus-fire", "Call one target in a 2v2", "In a 2v2, split damage can lose the first fight.",
           "If both players shoot different targets, neither duel ends quickly.",
           "Call the same opponent and trade immediately if the first swing misses.",
           "One fast advantage is easier to convert than two uncertain duels.",
           "Who should your team focus first?", 0),
    Tactic("cover-the-defuse", "Cover the defuser, not the bomb", "Your teammate starts the defuse. What are you watching?",
           "Looking at the bomb leaves the retake route open.",
           "Take the likely contact angle while your teammate commits to the defuse.",
           "One player buys time; the other completes the objective.",
           "Would you watch the bomb or the route?", 1),
    Tactic("regroup-after-pick", "Regroup after losing a teammate", "You are down a player. A solo revenge peek makes it worse.",
           "The opponent can hold for your predictable re-entry.",
           "Pause, trade utility, and create a two-player contact instead.",
           "You give the disadvantaged round a chance to become a winnable duel.",
           "Would you reset before the next fight?", 2),
    Tactic("watch-flank", "Assign the flank before you execute", "A clean entry can still fail to a late flank.",
           "Everyone staring forward leaves the route behind untracked.",
           "Agree who watches the flank before the team spends its utility.",
           "One clear job protects the execute without splitting the whole team.",
           "Who is responsible for the flank?", 3),
    Tactic("play-the-clock", "Make the clock work for you", "The clock is low. A late solo peek helps the defense.",
           "Every separate duel gives the defenders another chance to stall.",
           "Group up, clear the route that matters, and commit on one call.",
           "A shared timing gives the objective a better chance than hesitation.",
           "Do you group or gamble on a solo peek?", 4),
)

# Each route uses named callouts and their normalized radar coordinates from the
# callout index, instead of hand-guessed dot positions. Coordinates are resolved
# against the same map at render time.
MAP_CONTEXT: dict[str, tuple[str, str, str, str]] = {
    "trade-spacing": ("de_mirage", "MIRAGE", "Top Mid", "Connector"),
    "two-v-one": ("de_dust2", "DUST II", "Long A", "A Site"),
    "anti-eco": ("de_inferno", "INFERNO", "Apartments", "B Site"),
    "flash-entry": ("de_ancient", "ANCIENT", "Middle", "Donut"),
    "post-plant": ("de_mirage", "MIRAGE", "A Site", "Jungle"),
    "late-round": ("de_anubis", "ANUBIS", "A Main", "A Site"),
    "rotate-info": ("de_inferno", "INFERNO", "Middle", "Banana"),
    "reposition": ("de_dust2", "DUST II", "Long A", "Car"),
    "deny-isolation": ("de_anubis", "ANUBIS", "Middle", "A Main"),
    "retake-utility": ("de_ancient", "ANCIENT", "CT Spawn", "B Site"),
    "protect-utility": ("de_inferno", "INFERNO", "A Site", "Arch"),
    "trade-not-chase": ("de_mirage", "MIRAGE", "B Apartments", "B Site"),
    "sound-discipline": ("de_dust2", "DUST II", "B Tunnels", "B Site"),
    "crossfire": ("de_inferno", "INFERNO", "B Site", "Banana"),
    "hold-discipline": ("de_mirage", "MIRAGE", "A Ramp", "A Site"),
    "focus-fire": ("de_anubis", "ANUBIS", "B Main", "B Site"),
    "cover-the-defuse": ("de_ancient", "ANCIENT", "B Site", "CT Spawn"),
    "regroup-after-pick": ("de_anubis", "ANUBIS", "B Main", "Middle"),
    "watch-flank": ("de_mirage", "MIRAGE", "A Ramp", "Connector"),
    "play-the-clock": ("de_dust2", "DUST II", "Middle", "B Site"),
}

RADAR_BASE_URL = "https://raw.githubusercontent.com/MurkyYT/cs2-map-icons/main/images/radars"
CALLOUTS_BASE_URL = "https://raw.githubusercontent.com/UsrUnknow/cs2-radar-callouts/master/callouts"

CALLOUT_ALIASES: dict[str, tuple[str, ...]] = {
    "top mid": ("top mid", "middle", "mid"),
    "middle": ("middle", "mid"),
    "connector": ("connector", "connecter"),
    "a site": ("a site", "bombsite a", "bombsitea"),
    "b site": ("b site", "bombsite b", "bombsiteb"),
    "apartments": ("apartments", "apps", "b apartments"),
    "b apartments": ("b apartments", "apartments", "apps"),
    "long a": ("long a", "a long", "long"),
    "a ramp": ("a ramp", "ramp"),
    "b tunnels": ("b tunnels", "upper tunnels", "tunnels"),
    "ct spawn": ("ct spawn", "ct start", "ctspawn"),
    "arch": ("arch", "arch side"),
    "banana": ("banana", "b banana"),
    "donut": ("donut", "temple"),
    "a main": ("a main", "main"),
    "b main": ("b main", "main"),
    "car": ("car", "a car"),
}


def _normalize_callout(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _load_radar(map_id: str) -> Image.Image:
    """Load and cache official CS2 radar artwork for an episode's map."""
    cache_dir = Path(os.getenv("CS2_MAP_CACHE", "data/maps"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{map_id}_radar_psd.png"
    if not path.exists():
        request = urllib.request.Request(
            f"{RADAR_BASE_URL}/{map_id}_radar_psd.png",
            headers={"User-Agent": "CS2-Round-IQ/1.0 (automated video renderer)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                data = response.read()
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("map asset response was not a PNG")
            temp = path.with_suffix(".tmp")
            temp.write_bytes(data)
            temp.replace(path)
        except Exception as exc:
            raise RuntimeError(
                f"Could not fetch the CS2 radar for {map_id}; check GitHub Actions network access."
            ) from exc
    try:
        with Image.open(path) as source:
            return source.convert("RGBA")
    except Exception as exc:
        raise RuntimeError(f"Invalid cached CS2 radar image: {path}") from exc


def _load_callouts(map_id: str) -> dict[str, tuple[float, float]]:
    """Load normalized map callout anchors and cache them beside the radar."""
    cache_dir = Path(os.getenv("CS2_MAP_CACHE", "data/maps"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{map_id}_callouts.json"
    if not path.exists():
        request = urllib.request.Request(
            f"{CALLOUTS_BASE_URL}/{map_id}.json",
            headers={"User-Agent": "CS2-Round-IQ/1.0 (automated video renderer)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                data = response.read()
            payload = json.loads(data.decode("utf-8"))
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload), encoding="utf-8")
            temp.replace(path)
        except Exception as exc:
            raise RuntimeError(
                f"Could not fetch callout coordinates for {map_id}; check GitHub Actions network access."
            ) from exc
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid cached callout data: {path}") from exc

    if isinstance(payload, dict):
        entries = payload.get("callouts", payload.get("places", payload.get("locations", [])))
        if isinstance(entries, dict):
            entries = [dict(value, name=key) for key, value in entries.items() if isinstance(value, dict)]
    else:
        entries = payload
    if not isinstance(entries, list):
        raise RuntimeError(f"Unexpected callout data format for {map_id}")
    points: dict[str, tuple[float, float]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        try:
            x, y = float(entry["x"]), float(entry["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= x <= 1 and 0 <= y <= 1:
            points[_normalize_callout(entry["name"])] = (x, y)
    if not points:
        raise RuntimeError(f"No normalized callout coordinates found for {map_id}")
    return points


def _resolve_callout(points: dict[str, tuple[float, float]], name: str) -> tuple[float, float]:
    candidates = CALLOUT_ALIASES.get(name.lower(), (name.lower(),))
    for candidate in candidates:
        point = points.get(_normalize_callout(candidate))
        if point is not None:
            return point
    raise RuntimeError(f"Callout '{name}' is missing from this map's coordinate data")


@dataclass
class TacticCopy:
    title: str
    description: str
    tags: list[str]
    narration: str
    topic: str
    featured: dict
    hook_variant: str = "tactics"
    items: list[dict] | None = None


def build_tactic_copy(tactic: Tactic) -> TacticCopy:
    words = tactic.narration.split()
    if len(words) > 76:
        raise ValueError(f"Tactic narration is too long ({len(words)} words): {tactic.key}")
    if not tactic.hook.endswith("?") and len(tactic.hook.split()) > 12:
        raise ValueError(f"Tactic cold open must be short: {tactic.key}")
    title = f"CS2 Round IQ: {tactic.title}"
    _, map_name, source_callout, target_callout = MAP_CONTEXT[tactic.key]
    callout = f"{source_callout} → {target_callout}"
    description = (
        f"One CS2 tactical concept on the real {map_name} radar, around {callout}. "
        "The markers illustrate a tactical idea, not to scale, not captured demo data, "
        "and not an exact grenade lineup. "
        "Adapt it to your team, side and the current round.\n\n"
        "Map radar artwork © Valve Corporation; sourced from MurkyYT/cs2-map-icons.\n\n"
        "#CS2 #CounterStrike2 #CS2Tips #CS2Tactics"
    )
    return TacticCopy(title[:100], description, ["CS2", "Counter-Strike 2", "CS2 tactics", "CS2 tips"],
                      tactic.narration, "round_iq", {"name": tactic.title, "key": tactic.key})


def _wrap(text: str, max_chars: int = 28) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) <= max_chars or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines[:3]


def _background() -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    for y in range(0, H, 8):
        tint = int(12 * (y / H))
        draw.rectangle((0, y, W, min(H, y + 8)), fill=(BG[0] + tint // 3, BG[1] + tint, BG[2] + tint))
    return image


def _draw_frame(tactic: Tactic, episode: int, phase: int,
                radar: Image.Image | None = None,
                callout_positions: dict[str, tuple[float, float]] | None = None) -> Image.Image:
    if not 0 <= phase < 10:
        raise ValueError("Tactic frame phase must be between 0 and 9")
    image = _background()
    draw = ImageDraw.Draw(image)
    accent = (CYAN, CORAL, GOLD)[tactic.lane % 3]

    # Small, calm series marker; hook occupies the first two seconds.
    draw.rounded_rectangle((64, 68, 1016, 142), radius=24, fill=(20, 39, 53))
    draw.ellipse((91, 94, 111, 114), fill=accent)
    _text(draw, "CS2  /  ROUND IQ", (137, 105), 22, WHITE, True, anchor="lm")
    _text(draw, f"EP {episode:02d}", (979, 105), 20, MUTED, True, anchor="rm")

    headline_index = (0 if phase == 0 else 1 if phase <= 2 else 2 if phase <= 5
                      else 3 if phase <= 7 else 4)
    headlines = [tactic.hook, tactic.setup, tactic.action, tactic.payoff, "YOUR CALL"]
    headline = headlines[headline_index]
    lines = _wrap(headline, 27)
    font_size = 58 if len(lines) <= 2 else 49
    y = 222
    for line in lines:
        _text(draw, line, (64, y), font_size, WHITE if phase != 4 else accent, True)
        y += font_size + 18

    map_id, map_name, source_name, target_name = MAP_CONTEXT[tactic.key]
    callout = f"{source_name.upper()} → {target_name.upper()}"
    radar = radar or _load_radar(map_id)
    callout_positions = callout_positions or _load_callouts(map_id)
    start = _resolve_callout(callout_positions, source_name)
    target = _resolve_callout(callout_positions, target_name)
    bx1, by1, bx2, by2 = 74, 500, 1006, 1318
    draw.rounded_rectangle((bx1, by1, bx2, by2), radius=32, fill=(7, 12, 18), outline=(54, 79, 92), width=3)
    map_box = (bx1 + 28, by1 + 82, bx2 - 28, by2 - 24)
    map_w, map_h = map_box[2] - map_box[0], map_box[3] - map_box[1]
    fitted = ImageOps.contain(radar, (map_w, map_h))
    px = map_box[0] + (map_w - fitted.width) // 2
    py = map_box[1] + (map_h - fitted.height) // 2
    # Keep the authentic radar readable while giving it a restrained broadcast frame.
    image.paste(fitted.convert("RGB"), (px, py))
    draw.rounded_rectangle((bx1 + 20, by1 + 20, bx1 + 226, by1 + 70), radius=16,
                           fill=(9, 18, 27), outline=(57, 85, 99), width=2)
    _text(draw, map_name, (bx1 + 40, by1 + 45), 22, WHITE, True, anchor="lm")
    callout_box = (bx2 - 518, by1 + 20, bx2 - 20, by1 + 70)
    draw.rounded_rectangle(callout_box, radius=16, fill=(9, 18, 27), outline=accent, width=2)
    _text(draw, callout, ((callout_box[0] + callout_box[2]) // 2, by1 + 45),
          17, accent, True, anchor="mm")

    # Anchor each dot to the named callout's normalized point. We highlight the
    # locations in sequence instead of drawing a straight-line fake path.
    scale_x, scale_y = fitted.width, fitted.height
    def point(pos: tuple[float, float]) -> tuple[float, float]:
        return (px + pos[0] * scale_x, py + pos[1] * scale_y)

    a, b = point(start), point(target)
    placed_tags: list[tuple[int, int, int, int]] = []
    def location_tag(pos: tuple[float, float], text: str, color: tuple[int, int, int],
                     active: bool) -> None:
        x, y = pos
        font = _font(14, True)
        bbox = draw.textbbox((0, 0), text.upper(), font=font)
        text_w = bbox[2] - bbox[0]
        tag_w, tag_h = text_w + 22, 34
        candidates = ((x + 17, y - tag_h // 2), (x - tag_w - 17, y - tag_h // 2),
                      (x - tag_w // 2, y - tag_h - 17), (x - tag_w // 2, y + 17))
        boxes = []
        for left, top in candidates:
            left = min(max(px + 6, left), px + fitted.width - tag_w - 6)
            top = min(max(py + 6, top), py + fitted.height - tag_h - 6)
            boxes.append((left, top, left + tag_w, top + tag_h))
        def overlaps(box: tuple[int, int, int, int], other: tuple[int, int, int, int]) -> bool:
            return box[0] < other[2] + 8 and box[2] + 8 > other[0] and box[1] < other[3] + 8 and box[3] + 8 > other[1]
        tag = next((box for box in boxes if not any(overlaps(box, other) for other in placed_tags)), boxes[0])
        left, top, right, bottom = tag
        leader_x = min(max(x, left), right)
        leader_y = min(max(y, top), bottom)
        draw.line((x, y, leader_x, leader_y), fill=color, width=2)
        draw.rounded_rectangle((left, top, left + tag_w, top + tag_h), radius=10,
                               fill=(8, 15, 22), outline=color if active else (74, 91, 100), width=2)
        draw.text((left + tag_w // 2, top + tag_h // 2), text.upper(), font=font,
                  fill=color if active else (190, 200, 204), anchor="mm")
        placed_tags.append(tag)

    active_index = 0 if phase < 5 else 1
    for index, (pos, name, color) in enumerate(((a, source_name, CYAN),
                                                (b, target_name, CORAL))):
        x, y = pos
        active = index == active_index
        radius = 12
        if active:
            pulse = 31 + (phase % 3) * 5
            draw.ellipse((x-pulse, y-pulse, x+pulse, y+pulse), outline=color, width=3)
        draw.ellipse((x-radius-3, y-radius-3, x+radius+3, y+radius+3),
                     fill=(8, 17, 25), outline=color, width=4)
        draw.ellipse((x-5, y-5, x+5, y+5), fill=color)
        location_tag(pos, name, color, active)
    # Phase badge and animated progress indicator.
    labels = ["THE PROBLEM", "THE RISK", "THE RISK", "THE MOVE", "THE MOVE",
              "THE MOVE", "THE ADVANTAGE", "THE ADVANTAGE", "DISCUSS", "DISCUSS"]
    badge_w = 270
    draw.rounded_rectangle((W//2-badge_w//2, by2 + 25, W//2+badge_w//2, by2+80), radius=24,
                           fill=(24, 45, 59))
    _text(draw, labels[phase], (W//2, by2 + 52), 18, accent, True, anchor="mm")

    captions = [tactic.setup, tactic.action, tactic.action, tactic.payoff, tactic.payoff,
                tactic.payoff, tactic.question, tactic.question, tactic.question, tactic.question]
    cap_lines = _wrap(captions[phase], 36)
    cy = 1460
    for line in cap_lines:
        _text(draw, line, (64, cy), 30, WHITE, True)
        cy += 45
    if phase >= 8:
        _text(draw, "COMMENT YOUR PLAY", (64, 1618), 22, accent, True)
    # Progress dots identify the short's five distinct beats.
    for dot in range(10):
        x = 65 + dot * 31
        draw.rounded_rectangle((x, 1770, x+20, 1778), radius=4,
                               fill=accent if dot <= phase else (52, 68, 78))
    _text(draw, "CS2 TACTICS  ·  ORIGINAL TRAINING VISUAL", (64, 1832), 16, MUTED, False)
    return image


def _load_history(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        keys = payload.get("published", [])
        return [str(key) for key in keys] if isinstance(keys, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def choose_tactic(history_path: Path) -> tuple[Tactic, int]:
    used = _load_history(history_path)
    remaining = [item for item in TACTICS if item.key not in used]
    if not remaining:
        used = []
        remaining = list(TACTICS)
    tactic = remaining[0]
    return tactic, TACTICS.index(tactic) + 1


def _record_published(path: Path, tactic: Tactic) -> None:
    used = _load_history(path)
    if tactic.key not in used:
        used.append(tactic.key)
    if len(used) >= len(TACTICS):
        used = []
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"published": used}, indent=2), encoding="utf-8")
    tmp.replace(path)


def render_tactic(tactic: Tactic, episode: int, output_path: Path,
                  data_dir: Path, voice: str) -> tuple[float, TacticCopy]:
    from .media import _music_input, _synthesize, require_binary

    ffmpeg, ffprobe = require_binary("ffmpeg"), require_binary("ffprobe")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    copy = build_tactic_copy(tactic)
    audio = asyncio.run(_synthesize(copy.narration, voice, data_dir / "tactic-voice.mp3"))
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", str(audio)],
                           check=True, capture_output=True, text=True)
    speech_duration = float(probe.stdout.strip())
    if not 12 <= speech_duration <= 38:
        raise RuntimeError(f"Tactical narration must be 12–38 seconds, got {speech_duration:.2f}s")

    frame_dir = data_dir / f"tactic-{tactic.key}"
    frame_dir.mkdir(parents=True, exist_ok=True)
    map_id = MAP_CONTEXT[tactic.key][0]
    radar = _load_radar(map_id)
    callout_positions = _load_callouts(map_id)
    frames = []
    for phase in range(10):
        frame_path = frame_dir / f"phase-{phase}.png"
        _draw_frame(tactic, episode, phase, radar, callout_positions).save(frame_path, optimize=True)
        frames.append(frame_path)

    total = max(16.0, speech_duration + .35)
    first = min(2.15, total * .12)
    segment = (total - first) / 9
    durations = [first, *([segment] * 9)]
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for path, seconds in zip(frames, durations):
        command.extend(["-loop", "1", "-framerate", "30", "-t", f"{seconds:.4f}", "-i", str(path)])
    audio_input = len(frames)
    command.extend(["-i", str(audio)])
    music_args, music_filter = _music_input(ffmpeg, total, data_dir)
    music_input = audio_input + 1
    command.extend(music_args)

    filters = []
    for index, seconds in enumerate(durations):
        direction = "-" if index % 2 else "+"
        filters.append(
            f"[{index}:v]zoompan=z='min(zoom+0.00022,1.03)':"
            f"x='iw/2-(iw/zoom/2){direction}1.5*sin(on/30)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={W}x{H}:fps=30,trim=duration={seconds:.4f},setpts=PTS-STARTPTS,setsar=1[v{index}]"
        )
    filters.append("".join(f"[v{i}]" for i in range(len(frames))) + f"concat=n={len(frames)}:v=1:a=0[vfinal]")
    filters.append(f"[{audio_input}:a]aresample=44100,apad=whole_dur={total:.3f},loudnorm=I=-16:TP=-1.5:LRA=10[voice]")
    filters.append(f"[{music_input}:a]{music_filter}[bed]")
    filters.extend([
        "[voice]asplit=2[voice_mix][voice_key]",
        "[bed][voice_key]sidechaincompress=threshold=0.025:ratio=7:attack=12:release=280:makeup=1[ducked_bed]",
        "[voice_mix][ducked_bed]amix=inputs=2:duration=first:weights='1 0.60':normalize=0,alimiter=limit=0.95[aout]",
    ])
    command.extend(["-filter_complex", ";".join(filters), "-map", "[vfinal]", "-map", "[aout]",
                    "-t", f"{total:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(output_path)])
    subprocess.run(command, check=True, capture_output=True, text=True)
    verified = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=width,height",
                               "-of", "json", str(output_path)], check=True, capture_output=True, text=True)
    result = json.loads(verified.stdout)
    stream = result["streams"][0]
    final_duration = float(result["format"]["duration"])
    if (stream.get("width"), stream.get("height")) != (W, H):
        raise RuntimeError(f"Tactic Short has wrong dimensions: {stream.get('width')}x{stream.get('height')}")
    if final_duration < 12 or final_duration > 45:
        raise RuntimeError(f"Tactic Short duration outside 12–45 seconds: {final_duration:.2f}")
    return final_duration, copy


def run() -> Path:
    from .config import settings
    from .youtube import upload_video

    cfg = settings
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    history = cfg.data_dir / "tactics-history.json"
    tactic, episode = choose_tactic(history)
    now = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Lisbon"))
    run_id = os.getenv("GITHUB_RUN_ID") or now.strftime("%H%M%S")
    stamp = f"{now.strftime('%Y%m%d-%H%M')}-{run_id}"
    video_path = cfg.output_dir / f"{stamp}-round-iq-{tactic.key}.mp4"
    duration, copy = render_tactic(tactic, episode, video_path, cfg.data_dir / "render" / "tactics", cfg.voice)
    metadata = {"series": "CS2 Round IQ", "tactic_key": tactic.key, "episode": episode,
                "title": copy.title, "narration": copy.narration, "duration_seconds": round(duration, 2),
                "video_file": str(video_path), "upload_enabled": cfg.upload_enabled,
                "map": MAP_CONTEXT[tactic.key][1],
                "callouts": f"{MAP_CONTEXT[tactic.key][2]} → {MAP_CONTEXT[tactic.key][3]}",
                "visuals": "official CS2 radar with callout-anchored markers; not demo-derived"}
    metadata_path = video_path.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    log.info("Rendered CS2 Round IQ: %s (%s seconds)", video_path, round(duration, 1))
    if cfg.upload_enabled:
        video_id = upload_video(video_path, copy, cfg)
        metadata["youtube_video_id"] = video_id
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        _record_published(history, tactic)
        log.info("Published CS2 Round IQ: https://youtube.com/shorts/%s", video_id)
    return video_path


def main() -> None:
    from .config import settings

    logging.basicConfig(level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()


if __name__ == "__main__":
    main()
