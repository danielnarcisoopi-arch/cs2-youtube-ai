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

from PIL import Image, ImageDraw, ImageFont

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
    setup_positions: tuple[tuple[float, float], ...]
    target_positions: tuple[tuple[float, float], ...]
    lane: int

    @property
    def narration(self) -> str:
        return " ".join((self.hook, self.setup, self.action, self.payoff, self.question))


# These are general competitive fundamentals, not claims about exact map coordinates.
# The board is explicitly labelled as a concept diagram in every video.
TACTICS: tuple[Tactic, ...] = (
    Tactic("trade-spacing", "Trade spacing", "Your teammate gets picked. Can you trade it?",
           "If you are too far back, the duel is already over.",
           "Stay close enough to swing as the shot lands, then clear the same threat together.",
           "One player takes contact; the second converts it into a trade.",
           "Do you play close enough to trade?", ((.22,.72),(.25,.91),(.72,.25)), ((.22,.72),(.43,.55),(.72,.25)), 0),
    Tactic("two-v-one", "Turn a 2v1 into a crossfire", "In a 2v1, stop taking turns peeking.",
           "The defender only needs to win one clean duel at a time.",
           "Hold two different lines and swing on the same cue.",
           "Now one opponent has to clear both angles before the clock runs out.",
           "Would you hold or swing first?", ((.20,.78),(.20,.92),(.73,.34)), ((.34,.67),(.68,.48),(.49,.50)), 1),
    Tactic("anti-eco", "Respect the close range", "Against a low-buy, the close corner is the danger.",
           "A cheap weapon can still win a point-blank fight.",
           "Move as a pair, clear the nearest space, then take the long angle.",
           "You deny the isolated close duel the weaker buy needs.",
           "Do you clear close first?", ((.18,.77),(.70,.28),(.52,.18)), ((.30,.70),(.43,.58),(.70,.30)), 2),
    Tactic("flash-entry", "Flash for your teammate", "A flash is strongest when a teammate can use it.",
           "Throwing it after the entry has already stopped wastes the timing.",
           "Call the flash, turn away, then swing together as it pops.",
           "The utility creates the opening; the synchronized peek takes it.",
           "Do you call before you throw?", ((.20,.82),(.25,.92),(.72,.31)), ((.20,.82),(.48,.57),(.72,.31)), 3),
    Tactic("post-plant", "Stop re-peeking after plant", "The bomb is down. You do not need another duel.",
           "A solo peek gives the retake a free first fight.",
           "Fall into a crossfire, keep one player watching the defuse route, and trade contact.",
           "Make the retake clear two threats before it can touch the bomb.",
           "Would you hold the angle or chase?", ((.24,.62),(.74,.38),(.50,.17)), ((.38,.66),(.67,.41),(.50,.17)), 4),
    Tactic("late-round", "Group before the final hit", "Three players alive, but arriving one by one?",
           "Staggered entries give the defense three separate duels.",
           "Pause, share the last utility, and hit the space on one call.",
           "A grouped execute forces the defense to manage several threats at once.",
           "Do you reset or keep trickling in?", ((.17,.80),(.47,.91),(.78,.82)), ((.32,.68),(.43,.57),(.55,.68)), 0),
    Tactic("rotate-info", "Rotate on useful information", "One sound cue is not always a full commitment.",
           "A rushed rotation can leave the other site undefended.",
           "Have one player verify while the rest shift to safer positions.",
           "You protect the site and still keep the option to rotate together.",
           "Would you rotate on one sound?", ((.17,.54),(.20,.74),(.75,.50)), ((.29,.48),(.32,.69),(.64,.51)), 1),
    Tactic("reposition", "Reposition after the first kill", "You got the opening pick. They know your angle now.",
           "Holding the same line invites an instant trade.",
           "Fall back behind cover and make the next peek come from a new spot.",
           "The first kill gains space; the reposition keeps the advantage alive.",
           "Do you move after the pick?", ((.68,.29),(.48,.47),(.25,.77)), ((.52,.42),(.48,.54),(.25,.77)), 2),
    Tactic("deny-isolation", "Do not split your entry", "Two routes can still mean two isolated fights.",
           "If neither player can trade, the defense can take each duel safely.",
           "Use one route to draw attention while the second stays close enough to support.",
           "The goal is pressure with a trade, not distance for its own sake.",
           "Can your second player trade that route?", ((.18,.82),(.75,.82),(.51,.20)), ((.35,.68),(.49,.54),(.68,.69)), 3),
    Tactic("retake-utility", "Use utility before the retake", "Retaking through a held angle with no flash is a gift.",
           "The defender can take the first fight and fall back.",
           "Use a flash or smoke to break the angle, then clear together.",
           "Utility buys the space your team needs to start the retake.",
           "Would you spend the flash here?", ((.18,.81),(.38,.91),(.72,.77)), ((.25,.70),(.40,.67),(.65,.70)), 4),
    Tactic("protect-utility", "Keep one option for later", "Using every grenade on the first sighting can cost the round.",
           "The opponent may still have a second hit or a retake.",
           "Spend what wins space now, but keep a useful piece for the next phase.",
           "A planned reserve gives your team another answer when the round changes.",
           "What would you save for the retake?", ((.20,.75),(.45,.84),(.75,.75)), ((.28,.66),(.47,.76),(.65,.65)), 0),
    Tactic("trade-not-chase", "Trade the fight, not the kill", "Your teammate sees contact. Do not chase past them.",
           "Overrunning the angle can expose you to a second defender.",
           "Hold the trade distance, clear the next threat, then take the space together.",
           "You convert the first contact without donating another isolated duel.",
           "Would you chase or secure the trade?", ((.18,.75),(.30,.91),(.71,.30)), ((.25,.69),(.43,.59),(.66,.37)), 1),
    Tactic("sound-discipline", "Use sound without giving yours away", "You heard a rotation. Do not sprint into its path.",
           "Your own footsteps can reveal the position you meant to exploit.",
           "Slow down near the contact area and let the sound guide a safer move.",
           "Information is useful when your next action does not erase your advantage.",
           "Would you walk or run here?", ((.18,.70),(.47,.82),(.76,.38)), ((.29,.63),(.46,.70),(.67,.46)), 2),
    Tactic("crossfire", "Make the opponent clear two angles", "Two defenders on one line are easy to blind together.",
           "A single flash can remove both players from the fight.",
           "Separate the angles while staying close enough to trade.",
           "Now the attacker must expose themselves to one defender to fight the other.",
           "Would you stack or split the angle?", ((.25,.52),(.29,.60),(.74,.42)), ((.27,.47),(.65,.57),(.47,.53)), 3),
    Tactic("hold-discipline", "Do not abandon a strong angle early", "You have the angle. The urge to peek again is the trap.",
           "A second peek gives the opponent a timing they can prepare for.",
           "Hold, let your teammate gather info, and move only when the round calls for it.",
           "Discipline keeps the defense unpredictable.",
           "Would you re-peek for the highlight?", ((.72,.30),(.25,.73),(.47,.84)), ((.66,.34),(.31,.67),(.51,.77)), 4),
    Tactic("focus-fire", "Call one target in a 2v2", "In a 2v2, split damage can lose the first fight.",
           "If both players shoot different targets, neither duel ends quickly.",
           "Call the same opponent and trade immediately if the first swing misses.",
           "One fast advantage is easier to convert than two uncertain duels.",
           "Who should your team focus first?", ((.20,.74),(.73,.72),(.50,.28)), ((.32,.62),(.63,.62),(.52,.42)), 0),
    Tactic("cover-the-defuse", "Cover the defuser, not the bomb", "Your teammate starts the defuse. What are you watching?",
           "Looking at the bomb leaves the retake route open.",
           "Take the likely contact angle while your teammate commits to the defuse.",
           "One player buys time; the other completes the objective.",
           "Would you watch the bomb or the route?", ((.30,.62),(.73,.37),(.49,.17)), ((.39,.62),(.66,.43),(.49,.17)), 1),
    Tactic("regroup-after-pick", "Regroup after losing a teammate", "You are down a player. A solo revenge peek makes it worse.",
           "The opponent can hold for your predictable re-entry.",
           "Pause, trade utility, and create a two-player contact instead.",
           "You give the disadvantaged round a chance to become a winnable duel.",
           "Would you reset before the next fight?", ((.18,.33),(.48,.84),(.76,.69)), ((.31,.46),(.43,.65),(.65,.60)), 2),
    Tactic("watch-flank", "Assign the flank before you execute", "A clean entry can still fail to a late flank.",
           "Everyone staring forward leaves the route behind untracked.",
           "Agree who watches the flank before the team spends its utility.",
           "One clear job protects the execute without splitting the whole team.",
           "Who is responsible for the flank?", ((.20,.79),(.40,.90),(.66,.84)), ((.31,.69),(.48,.76),(.65,.65)), 3),
    Tactic("play-the-clock", "Make the clock work for you", "The clock is low. A late solo peek helps the defense.",
           "Every separate duel gives the defenders another chance to stall.",
           "Group up, clear the route that matters, and commit on one call.",
           "A shared timing gives the objective a better chance than hesitation.",
           "Do you group or gamble on a solo peek?", ((.18,.83),(.48,.91),(.77,.83)), ((.31,.69),(.43,.61),(.56,.69)), 4),
)


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
    description = (
        f"One CS2 tactical concept: {tactic.title}. The animation is an original concept diagram, "
        "not an exact in-game map or a claim about fixed coordinates. Use it to discuss the decision, "
        "then adapt it to your team and the current round.\n\n"
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


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float],
           color: tuple[int, int, int], width: int = 9) -> None:
    draw.line((start, end), fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 25
    left = (end[0] - length * math.cos(angle - .48), end[1] - length * math.sin(angle - .48))
    right = (end[0] - length * math.cos(angle + .48), end[1] - length * math.sin(angle + .48))
    draw.polygon((end, left, right), fill=color)


def _background() -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    for y in range(0, H, 8):
        tint = int(12 * (y / H))
        draw.rectangle((0, y, W, min(H, y + 8)), fill=(BG[0] + tint // 3, BG[1] + tint, BG[2] + tint))
    return image


def _draw_frame(tactic: Tactic, episode: int, phase: int) -> Image.Image:
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

    # Diagram is an abstract training board. It intentionally avoids map names/coordinates.
    bx1, by1, bx2, by2 = 74, 500, 1006, 1318
    draw.rounded_rectangle((bx1, by1, bx2, by2), radius=38, fill=PANEL, outline=(54, 79, 92), width=3)
    for x in range(bx1 + 36, bx2, 70):
        draw.line((x, by1 + 28, x, by2 - 28), fill=GRID, width=1)
    for yy in range(by1 + 32, by2, 70):
        draw.line((bx1 + 28, yy, bx2 - 28, yy), fill=GRID, width=1)
    draw.rounded_rectangle((bx1 + 38, by1 + 38, bx2 - 38, by2 - 38), radius=30,
                           outline=(64, 91, 103), width=5)
    # Five abstract board geometries keep the series visually varied without claiming
    # to reproduce a real CS2 map or exact grenade lineup.
    lane_color = (73, 102, 113)
    left, right = bx1 + 70, bx2 - 70
    top, bottom = by1 + 105, by2 - 80
    middle_x, middle_y = W // 2, (top + bottom) // 2
    layout = tactic.lane % 5
    if layout == 0:  # open lanes
        for offset in (-1, 0, 1):
            ymid = middle_y + offset * 116
            draw.line((left, ymid, right, ymid), fill=lane_color, width=11)
        blocks = ((bx1+265,by1+145,bx1+405,by1+285),(bx1+620,by1+424,bx1+760,by1+565),(bx1+375,by1+624,bx1+555,by1+722))
    elif layout == 1:  # offset S route
        draw.line((left, bottom-65, bx1+390, middle_y+120, bx2-390, middle_y-100, right, top+100), fill=lane_color, width=13, joint="curve")
        draw.line((bx1+390,middle_y+120,bx1+390,top+120), fill=lane_color, width=10)
        draw.line((bx2-390,middle_y-100,bx2-390,bottom-75), fill=lane_color, width=10)
        blocks = ((bx1+180,by1+145,bx1+315,by1+275),(bx1+650,by1+420,bx1+810,by1+565),(bx1+390,by1+570,bx1+565,by1+690))
    elif layout == 2:  # T junction
        draw.line((middle_x, top, middle_x, bottom), fill=lane_color, width=13)
        draw.line((left, middle_y-130, right, middle_y-130), fill=lane_color, width=11)
        draw.line((left, middle_y+135, right, middle_y+135), fill=lane_color, width=11)
        blocks = ((bx1+180,by1+340,bx1+330,by1+485),(bx1+650,by1+155,bx1+805,by1+305),(bx1+650,by1+620,bx1+810,by1+755))
    elif layout == 3:  # crossing routes
        draw.line((left, top+120, right, bottom-120), fill=lane_color, width=13)
        draw.line((left, bottom-120, right, top+120), fill=lane_color, width=13)
        draw.line((middle_x, top, middle_x, bottom), fill=(54,78,90), width=7)
        blocks = ((bx1+205,by1+165,bx1+355,by1+310),(bx1+655,by1+165,bx1+805,by1+310),(bx1+420,by1+600,bx1+590,by1+735))
    else:  # connected rooms
        draw.line((left, middle_y, right, middle_y), fill=lane_color, width=12)
        draw.line((middle_x, top, middle_x, bottom), fill=lane_color, width=12)
        draw.line((bx1+280,by1+230,bx1+420,by1+390), fill=(54,78,90), width=8)
        draw.line((bx1+680,by1+540,bx1+820,by1+690), fill=(54,78,90), width=8)
        blocks = ((bx1+180,by1+155,bx1+340,by1+315),(bx1+650,by1+155,bx1+810,by1+315),(bx1+400,by1+580,bx1+580,by1+740))
    for index, box in enumerate(blocks):
        draw.rounded_rectangle(box, radius=18 if index < 2 else 26,
                               fill=(28, 46, 58), outline=(82, 111, 121), width=3)
    _text(draw, "CONCEPT DIAGRAM  ·  NOT TO SCALE", (W // 2, by1 + 30), 17, MUTED, True, anchor="mt")

    def point(pos: tuple[float, float]) -> tuple[float, float]:
        return (bx1 + pos[0] * (bx2 - bx1), by1 + pos[1] * (by2 - by1))

    start, target = tactic.setup_positions, tactic.target_positions
    if phase <= 2:
        positions = start
    elif phase <= 5:
        t = min(.82, (phase - 2) * .27)
        positions = tuple((a[0] * (1-t) + b[0] * t, a[1] * (1-t) + b[1] * t) for a, b in zip(start, target))
    else:
        positions = target

    # A short movement every scene plus a highlighted route makes the visual teach the action.
    if 3 <= phase <= 5:
        progress = min(1.0, (phase - 2) / 3)
        for i, (a, b) in enumerate(zip(start[:2], target[:2])):
            partial = (a[0] * (1-progress) + b[0] * progress,
                       a[1] * (1-progress) + b[1] * progress)
            _arrow(draw, point(a), point(partial), accent if i == 0 else GOLD, width=8)
    elif phase == 0:
        _arrow(draw, point(start[0]), point(start[2]), (104, 124, 135), width=5)

    if phase == 2:
        x, yy = point(start[0])
        draw.ellipse((x-66, yy-66, x+66, yy+66), outline=GOLD, width=6)
    if phase == 7:
        for pos in target[:2]:
            x, yy = point(pos)
            draw.ellipse((x-56, yy-56, x+56, yy+56), outline=GOLD, width=5)

    for idx, pos in enumerate(positions):
        color = CYAN if idx < 2 else CORAL
        x, yy = point(pos)
        radius = 34
        draw.ellipse((x-radius-6, yy-radius-6, x+radius+6, yy+radius+6), fill=(10, 17, 25), outline=color, width=6)
        draw.ellipse((x-radius, yy-radius, x+radius, yy+radius), fill=color)
        _text(draw, "T" if idx < 2 else "CT", (x, yy), 18, BG, True, anchor="mm")
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
    frames = []
    for phase in range(10):
        frame_path = frame_dir / f"phase-{phase}.png"
        _draw_frame(tactic, episode, phase).save(frame_path, optimize=True)
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
                "visuals": "original animated concept diagrams; not to scale"}
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
