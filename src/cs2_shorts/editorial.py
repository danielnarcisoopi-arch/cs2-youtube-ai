"""Evidence-first editorial Shorts. Independent of the market/clip pipelines."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


from .scripts import VideoCopy, _spoken_name

log = logging.getLogger(__name__)
FORMATS = ('budget', 'duel', 'loadout', 'wear', 'premium_budget', 'popular', 'watchlist')
WEAPONS = ('AK-47', 'M4A1-S', 'M4A4', 'AWP', 'USP-S', 'Glock-18', 'Desert Eagle', 'MP9', 'MAC-10')
WEARS = ('Factory New', 'Minimal Wear', 'Field-Tested', 'Well-Worn', 'Battle-Scarred')


def base_name(name: str) -> str:
    return re.sub(r' \((?:' + '|'.join(WEARS) + r')\)$', '', name)


def money(value: float, currency: str) -> str:
    return {'USD': '$', 'EUR': '€', 'GBP': '£'}.get(currency, currency + ' ') + f'{value:,.2f}'


@dataclass
class Plan:
    format: str
    title: str
    items: list[dict]
    labels: list[str]
    hook: str
    outro: str
    currency: str
    budget: float | None = None

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps([self.format, sorted(base_name(x['name']) for x in self.items),
                                         self.currency, self.budget]).encode()).hexdigest()[:20]


def eligible_rows(rows: list[dict], catalog: list[dict]) -> list[dict]:
    """Only in-stock *listing* prices and exact canonical artwork; never estimates."""
    names = {x.get('market_hash_name') for x in catalog if x.get('image')}
    output = []
    for row in rows:
        name = str(row.get('market_hash_name', ''))
        price = row.get('min_price')
        if (name not in names or not any(name.startswith(w + ' | ') for w in WEAPONS)
                or not any(name.endswith('(' + w + ')') for w in WEARS)):
            continue
        if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0 or int(row.get('quantity') or 0) < 1:
            continue
        output.append({'name': name, 'price': float(price), 'quantity': int(row['quantity']),
                       'weapon': name.split(' | ')[0], 'source': 'Skinport',
                       'item_page': row.get('item_page')})
    return output


def make_plans(rows: list[dict], history: list[dict], currency: str, rng: random.Random) -> list[Plan]:
    # Wear/StatTrak changes cannot sneak the same finish back into the next video.
    recent = {name for h in history[-12:] for name in h['skins']}
    fresh = [x for x in rows if base_name(x['name']) not in recent]
    rng.shuffle(fresh)
    unique = list({base_name(x['name']): x for x in fresh}.values())
    plans = []

    def add(fmt, title, items, labels, hook, outro, budget=None):
        if len(items) >= 2:
            plans.append(Plan(fmt, title[:100], items, labels, hook, outro, currency, budget))

    for cap in (5, 10, 20):
        for weapon in WEAPONS:
            pool = [x for x in unique if x['weapon'] == weapon and x['price'] < cap]
            if len(pool) >= 3:
                add('budget', f'3 {weapon} Skins Under {money(cap, currency)} — Which Wins?', pool[:3],
                    ['THE FIRST PICK', 'THE CHALLENGER', 'YOUR FINAL OPTION'],
                    'Your next skin does not need a premium price. Which finish wins?',
                    'Pick your winner: first, second, or third?', cap)
            if len(pool) >= 2:
                add('duel', f'{weapon} Skin Battle: Both Under {money(cap, currency)}', pool[:2],
                    ['OPTION A', 'OPTION B'], 'Same weapon. Two different finishes. You can only keep one.',
                    'Option A or option B? Defend your choice.', cap)
    for cap in (25, 50, 100, 300):
        selected = []
        for weapons in (('AK-47',), ('M4A1-S', 'M4A4'), ('USP-S', 'Glock-18', 'Desert Eagle')):
            pool = [x for x in unique if x['weapon'] in weapons and x['price'] <= cap / 3]
            if pool:
                selected.append(pool[0])
        if len(selected) == 3 and sum(x['price'] for x in selected) < cap:
            total = money(sum(x['price'] for x in selected), currency)
            add('loadout', f'Would You Equip This {total} CS2 Loadout?', selected,
                ['T-SIDE RIFLE', 'CT-SIDE RIFLE', 'PISTOL PICK'],
                'Three slots. One loadout budget. Would you equip all of these?',
                f'The combined lowest listings total {total}. Which slot would you change?', cap)
    by_base = {}
    for x in fresh:
        by_base.setdefault(base_name(x['name']), []).append(x)
    for name, variants in by_base.items():
        variants = sorted(variants, key=lambda x: x['price'])
        if len(variants) > 1 and variants[-1]['price'] > variants[0]['price'] * 1.3:
            add('wear', f'{name}: Is the Higher Asking Price Worth It?', [variants[0], variants[-1]],
                ['LOWER ASK', 'HIGHER ASK'], 'Same finish, different wear categories. Look before paying more.',
                'Catalog images are illustrative. Inspect the actual float and pattern before buying.')
    for weapon in WEAPONS:
        pool = [x for x in unique if x['weapon'] == weapon]
        cheap = [x for x in pool if x['price'] < 10]
        pricey = [x for x in pool if x['price'] >= 50]
        if cheap and pricey:
            add('premium_budget', f'{weapon}: Budget Finish vs Premium Price', [cheap[0], pricey[0]],
                ['BUDGET SIDE', 'PREMIUM SIDE'], 'Forget the price tag for a second. Which finish would you actually equip?',
                'Would you pay the difference, or keep the budget finish?')
    stock = sorted(unique, key=lambda x: x['quantity'], reverse=True)
    if len(stock) >= 3:
        offset = rng.randrange(min(10, len(stock) - 2))
        chosen = stock[offset:offset + 3]
        add('popular', '3 CS2 Skins With Plenty of Listings — Your Pick?', chosen,
            ['PICK ONE', 'PICK TWO', 'PICK THREE'],
            'Plenty of listings does not make a skin better. Which of these deserves a loadout slot?',
            'Listing counts are supply, not completed sales. Which finish gets your vote?')
    watch = [x for x in unique if x['price'] < 20]
    if len(watch) >= 3:
        add('watchlist', f'3 CS2 Skins Under {money(20, currency)} to Compare', watch[:3],
            ['COMPARE THE FINISH', 'CHECK THE WEAR', 'CHECK THE ASK'],
            'A cheap listing is a starting point, not an investment thesis. Compare these finishes.',
            'No profit prediction here. Fees and price changes matter. Which would you inspect first?', 20)
    used = {h['fingerprint'] for h in history}
    return [p for p in plans if p.fingerprint not in used]


def select_plan(plans: list[Plan], history: list[dict], rng: random.Random, requested='auto') -> Plan:
    if requested != 'auto':
        plans = [p for p in plans if p.format == requested]
    if not plans:
        raise RuntimeError('No fresh, verified topic is available. Refusing to repeat an old video or invent prices.')
    # Rotate all feasible formats before returning to the same type.
    last_seen = {fmt: max((i for i, h in enumerate(history) if h['format'] == fmt), default=-1)
                 for fmt in FORMATS}
    oldest = min(last_seen[p.format] for p in plans)
    return rng.choice([p for p in plans if last_seen[p.format] == oldest])


def validate_creative(payload: dict, count: int) -> None:
    if not isinstance(payload, dict) or set(payload) != {'hook', 'beats', 'outro'}:
        raise ValueError('Invalid editorial script fields')
    if not isinstance(payload['beats'], list) or len(payload['beats']) != count:
        raise ValueError('AI script does not match the selected visual beats')
    for line in [payload['hook'], *payload['beats'], payload['outro']]:
        if not isinstance(line, str) or not 3 <= len(line.split()) <= 16:
            raise ValueError('Each editorial beat must contain three to sixteen words')
        if re.search(r'\d|[$€£]|\b(profit|guaranteed|investment|invest|undervalued|rare|rarity|dragon lore|sticker|float|pattern|sales|volume|percent|dollars|euros|pounds|cheapest|best|buy now)\b', line, re.I):
            raise ValueError('AI added an unverified price, market claim, or unsupported detail')


def creative_script(plan: Plan, history: list[dict], key: str) -> dict:
    import requests
    from .config import settings
    from .media import _skin_catalog
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {'hook': {'type': 'string'}, 'beats': {'type': 'array', 'items': {'type': 'string'}},
                             'outro': {'type': 'string'}}, 'required': ['hook', 'beats', 'outro']}
    content = [{'type': 'input_text', 'text': json.dumps({
        'brief': 'Write an English CS2 Short. Fresh conversational hook, one commentary beat per image, final comment question. '
                 'Three to sixteen words per line. No digits, money, prices, weapon names, rarity, sales, profit, investment, '
                 'stickers, actual wear/float assertions or unsupported facts. Prices and exact item names are added by code. '
                 'Use visible colors and design details from the supplied images, framed as subjective opinions. '
                 'Avoid generic filler and all openings from recent scripts. Catalog artwork is illustrative.',
        'format': plan.format, 'title': plan.title,
        'recent_hooks': [h.get('hook', '') for h in history[-20:]],
        'items_in_order': [{'name': x['name']} for x in plan.items]})}]
    catalog = _skin_catalog(settings.data_dir / 'editorial-render', settings.image_timeout)
    index = {x.get('market_hash_name'): x for x in catalog}
    for item in plan.items:
        content.append({'type': 'input_image', 'image_url': index[item['name']]['image'], 'detail': 'low'})
    response = requests.post('https://api.openai.com/v1/responses',
        headers={'Authorization': f'Bearer {key}'}, timeout=(10, 90),
        json={'model': os.getenv('EDITORIAL_AI_MODEL', 'gpt-4.1-mini'), 'store': False,
              'input': [{'role': 'user', 'content': content}],
              'text': {'format': {'type': 'json_schema', 'name': 'skin_short', 'strict': True, 'schema': schema}}})
    response.raise_for_status()
    body = response.json()
    if body.get('status') != 'completed':
        raise ValueError('AI response was not completed')
    output = ''.join(c.get('text', '') for m in body.get('output', []) for c in m.get('content', [])
                     if c.get('type') == 'output_text')
    script = json.loads(output)
    validate_creative(script, len(plan.items))
    if script['hook'].casefold() in {h.get('hook', '').casefold() for h in history}:
        raise ValueError('AI reused an earlier hook')
    return script


def build_editorial_copy(plan: Plan, script: dict | None, captured: str) -> VideoCopy:
    hook, outro = (script['hook'], script['outro']) if script else (plan.hook, plan.outro)
    lines = [hook]
    for i, item in enumerate(plan.items):
        wear = item['name'].rsplit('(', 1)[-1].rstrip(')')
        detail = script['beats'][i] if script else f"{plan.labels[i].capitalize()}. Which finish fits your style?"
        lines.append(f"{_spoken_name(item['name'])}. {wear}. {money(item['price'], plan.currency)}. {detail}")
    # Always retain the evidence-specific ending, even if the AI writes a CTA.
    lines.append((plan.outro + ' ' + outro) if script else outro)
    facts = '\n'.join(f"- {x['name']}: {money(x['price'], plan.currency)} ({x['quantity']} listings)"
                      + (f"\n  {x['item_page']}" if x.get('item_page') else '') for x in plan.items)
    description = (f"{plan.title}\n\nSkinport lowest asking prices in {plan.currency}, captured {captured}.\n"
                   f"{facts}\n\nPrices change; asking prices are not completed sales. Fees are excluded. "
                   "Catalog images illustrate the named skin and may not represent an individual listing's float or pattern. "
                   "Picks are subjective, not investment recommendations.\n"
                   "Data: https://skinport.com/\nArt: https://github.com/ByMykel/CSGO-API\n"
                   "#CS2 #CS2Skins #CounterStrike2 #Shorts")
    return VideoCopy(title=plan.title, description=description, tags=['CS2', 'CS2 skins', 'loadout', 'Shorts'],
                     narration=' '.join(lines), topic=plan.format, featured=plan.items[0],
                     items=plan.items, scene_lines=lines,
                     scene_labels=[plan.title, *plan.labels, 'YOUR TURN'], series='editorial')


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    history = json.loads(path.read_text())
    if not isinstance(history, list):
        raise ValueError('Invalid editorial history; refusing to silently reset duplicate protection')
    for h in history:
        if not isinstance(h, dict) or not {'skins', 'fingerprint', 'format'} <= h.keys():
            raise ValueError('Malformed editorial history')
    return history


def write_history(path: Path, history: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(history, indent=2), encoding='utf-8')
    temp.replace(path)


def run(requested='auto', plan_only=False, template_mode=False) -> Path:
    from .config import settings, validate_settings
    from .media import _skin_catalog, render_video
    from .providers.skinport import SkinportProvider
    from .youtube import upload_video
    validate_settings()
    key = os.getenv('OPENAI_API_KEY', '')
    if not key and not template_mode:
        raise RuntimeError('Add OPENAI_API_KEY to repository secrets for AI editorial scripts. '
                           'For a non-AI preview only, use --template-mode.')
    if template_mode and settings.upload_enabled:
        raise RuntimeError('Template mode is preview-only; AI scripts are required for publishing this series.')
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    history_path = settings.data_dir / 'editorial-history.json'
    history = load_history(history_path)
    provider = SkinportProvider(currency=settings.currency)
    # Use raw documented listings to exclude suggested_price fallback entirely.
    raw = provider._get('items')
    captured = datetime.now(timezone.utc).isoformat()
    catalog = _skin_catalog(settings.data_dir / 'editorial-render', settings.image_timeout)
    rows = eligible_rows(raw, catalog)
    rng = random.Random(os.urandom(32))
    plan = select_plan(make_plans(rows, history, settings.currency, rng), history, rng, requested)
    script = None
    if key:
        for attempt in range(3):
            try:
                script = creative_script(plan, history, key)
                break
            except (ValueError, KeyError) as exc:
                if attempt == 2:
                    raise RuntimeError('AI script failed editorial validation three times; publishing blocked') from exc
                log.warning('AI script rejected by editorial validation; regenerating (%s/3)', attempt + 1)
    copy = build_editorial_copy(plan, script, captured)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(3).hex()
    stem = settings.output_dir / f'editorial-{stamp}'
    metadata = {'captured_at': captured, 'plan': asdict(plan), 'fingerprint': plan.fingerprint,
                'script_source': 'OpenAI visual-grounded script' if script else 'non-AI preview template',
                'hook': copy.scene_lines[0], 'scene_lines': copy.scene_lines, 'title': copy.title,
                'description': copy.description, 'status': 'planned'}
    target = stem.with_suffix('.json')
    target.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    if plan_only:
        return target
    video = stem.with_suffix('.mp4')
    # Moving catalog art is deliberate: no unrelated gameplay, no misrepresented craft.
    duration = render_video(copy, settings.currency, settings.data_dir / 'editorial-render', video,
                            settings.voice, True, settings.image_timeout, False)
    metadata.update(status='rendered', duration_seconds=duration)
    target.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    # Reserve before upload: a network error after YouTube accepts the video must not
    # cause an automated rerun to repeat the same topic. Never retry videos.insert here.
    entry = {'format': plan.format, 'fingerprint': plan.fingerprint,
             'skins': sorted({base_name(x['name']) for x in plan.items}),
             'hook': copy.scene_lines[0], 'captured_at': captured, 'status': 'rendered', 'title': copy.title}
    history.append(entry)
    write_history(history_path, history)
    if settings.upload_enabled:
        entry['status'] = 'upload_pending'
        write_history(history_path, history)
        video_id = upload_video(video, copy, settings)
        entry.update(status='published', youtube_video_id=video_id)
        metadata.update(status='published', youtube_video_id=video_id)
        write_history(history_path, history)
        target.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return video


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--format', choices=('auto', *FORMATS), default='auto')
    parser.add_argument('--plan-only', action='store_true', help='Write evidence and script without rendering or publishing')
    parser.add_argument('--template-mode', action='store_true', help='Explicit non-AI preview; publishing disabled')
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    log.info('Created %s', run(args.format, args.plan_only, args.template_mode))


if __name__ == '__main__':
    main()
