"""Mobile-safe editorial cards with verified skin art and scene-aligned captions."""
from __future__ import annotations

import hashlib
from pathlib import Path
from PIL import Image, ImageDraw

from .media import _background, _draw_weapon, _font, _skin_image, _text, _wrap_name, WHITE, MUTED
from .scripts import VideoCopy

ACCENTS = {'budget': (151,255,80), 'duel': (127,175,255), 'loadout': (197,153,255),
           'wear': (255,195,108), 'premium_budget': (255,135,174),
           'popular': (97,232,220), 'watchlist': (159,189,255)}


def block(draw, text, xy, size, color, width=880, max_lines=4):
    words, lines, current = text.split(), [], ''
    for word in words:
        test = (current + ' ' + word).strip()
        if draw.textlength(test, font=_font(size, True)) > width and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        return block(draw, text, xy, size - 4, color, width, max_lines) if size > 22 else None
    for i, line in enumerate(lines):
        _text(draw, line, (xy[0], xy[1] + i * (size + 12)), size, color, True)


def make_editorial_scenes(copy: VideoCopy, currency: str, data_dir: Path, timeout: int) -> list[Path]:
    from .editorial import money
    data_dir.mkdir(parents=True, exist_ok=True)
    accent = ACCENTS[copy.topic]
    art = []
    for item in copy.items:
        path = data_dir / ('art-' + hashlib.sha256(item['name'].encode()).hexdigest()[:18] + '.img')
        if not _skin_image(item['name'], path, timeout):
            raise RuntimeError(f"Exact art missing for {item['name']}; editorial publishing blocked")
        art.append(path)
    paths = []
    total = sum(x['price'] for x in copy.items)
    for i in range(len(copy.items) + 2):
        index = min(max(i - 1, 0), len(art) - 1)
        frame = _background(i, accent, art[index])
        draw = ImageDraw.Draw(frame)
        _text(draw, 'CS2 / SKIN STORIES', (76, 160), 25, accent, True)
        _text(draw, copy.topic.replace('_', ' ').upper(), (76, 213), 20, MUTED, True)
        if i == 0:
            block(draw, copy.title, (76, 305), 62, WHITE, max_lines=4)
            for j, path in enumerate(art):
                y = 760 + j * 220
                _draw_weapon(frame, path, (90, y, 970, y + 250), .95)
            block(ImageDraw.Draw(frame), copy.scene_lines[0], (76, 1510), 30, WHITE, max_lines=3)
        elif i == len(copy.items) + 1:
            block(draw, 'WHICH ONE\nWOULD YOU EQUIP?', (76, 330), 65, WHITE, max_lines=3)
            for j, path in enumerate(art):
                y = 700 + j * 220
                _draw_weapon(frame, path, (150, y, 970, y + 230), .92)
                _text(ImageDraw.Draw(frame), chr(65 + j), (80, y + 100), 40, accent, True)
            if copy.topic == 'loadout':
                _text(ImageDraw.Draw(frame), 'TOTAL ' + money(total, currency), (76, 1440), 52, accent, True)
            block(ImageDraw.Draw(frame), 'Comment your pick. Follow for a different skin story.', (76, 1540), 33, WHITE)
        else:
            item = copy.items[index]
            _text(draw, f'{index + 1:02d} / {len(copy.items):02d}', (76, 292), 28, accent, True)
            block(draw, copy.scene_labels[i], (76, 365), 48, WHITE, max_lines=2)
            # Center the weapon above the price and lower-right Shorts controls.
            _draw_weapon(frame, art[index], (25, 610, 1030, 1160), 1.05)
            draw = ImageDraw.Draw(frame)
            for n, line in enumerate(_wrap_name(item['name'], max_width=850, size=34)):
                _text(draw, line, (76, 1200 + 45 * n), 34, WHITE, True)
            _text(draw, money(item['price'], currency), (76, 1340), 80, accent, True)
            _text(draw, 'SKINPORT LOWEST ASK / ' + currency, (78, 1445), 22, MUTED, True)
            # Burned-in exact speech is aligned with this item's image and narration.
            block(draw, copy.scene_lines[i], (76, 1510), 27, WHITE, width=840, max_lines=4)
        _text(ImageDraw.Draw(frame), 'Catalog art · Prices change · Inspect actual item', (76, 1770), 20, MUTED)
        path = data_dir / f'beat-{i + 1:02d}.png'
        frame.save(path)
        paths.append(path)
    if copy.promo_seconds:
        intro = promo_frame(copy, accent, data_dir / 'promo-intro.png', True)
        outro = promo_frame(copy, accent, data_dir / 'promo-outro.png', False)
        return [intro, *paths, outro]
    return paths


def promo_frame(copy: VideoCopy, accent: tuple, output: Path, intro: bool) -> Path:
    from .promotion import PROMO_MESSAGE, PROMO_URL
    frame = _background(0, accent)
    draw = ImageDraw.Draw(frame)
    _text(draw, 'CS2 / SKIN STORIES', (76, 160), 25, accent, True)
    block(draw, copy.title if intro else 'YOUR NEXT SKIN STARTS HERE',
          (76, 290), 58, WHITE, width=880, max_lines=4)
    draw.rounded_rectangle((64, 680, 1016, 1190), radius=40,
                           fill=(9, 16, 24), outline=accent, width=5)
    title, cta = PROMO_MESSAGE.split(', ', 1)
    _text(draw, title, (540, 820), 78, accent, True, anchor='mm')
    _text(draw, cta, (540, 945), 39, WHITE, True, anchor='mm')
    url = PROMO_URL.split('://', 1)[-1]
    _text(draw, url, (540, 1080), 38, accent, True, anchor='mm')
    if intro:
        _text(draw, 'VIDEO STARTS IN', (540, 1330), 29, accent, True, anchor='mm')
        draw.ellipse((415, 1355, 665, 1605), outline=accent, width=4)
        # Numerals are overlaid by FFmpeg on the video clock, after zoom.
    else:
        block(draw, 'Link in description', (76, 1390), 52, WHITE, max_lines=2)
    _text(draw, 'PROMOTION', (76, 1750), 22, MUTED, True)
    frame.save(output)
    return output
