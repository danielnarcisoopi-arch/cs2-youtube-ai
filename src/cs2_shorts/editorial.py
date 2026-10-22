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
from .promotion import add_promo_link

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


# Local editorial openings, selected against recent history. No language-model service.
HOOKS = {
    'budget': (
        'Three finishes, one price ceiling. Which one deserves your next loadout slot?',
        'A tight budget still leaves choices. Here are three for the same weapon.',
        'Before spending more, compare these three affordable finishes side by side.',
        'Your next upgrade could cost less than you think. Pick your favorite finish.',
        'Same weapon, three budget options. Which one would you actually equip?',
        'Skip the expensive section for a moment. These picks stay below the budget.'),
    'duel': (
        'Same weapon. Two finishes. You can only equip one. What is your pick?',
        'Option A versus option B. Let the finish decide before the price does.',
        'Two skins enter your shortlist. Only one gets the loadout slot.',
        'Make your pick now, then check whether the price changes your answer.',
        'One weapon slot, two choices. Which side are you taking today?',
        'Would you choose the cheaper finish, or pay the difference for the other?'),
    'loadout': (
        'One rifle for each side, plus a pistol. Would you equip this combination?',
        'Build a loadout around three slots. Here is what the total buys today.',
        'Forget buying one expensive skin. What about spreading the budget across three slots?',
        'Three weapons share one budget. Which slot would you upgrade first?',
        'Your next loadout starts here. Keep the combination or replace one piece?',
        'A rifle for each side and a pistol finish. Does this loadout work for you?'),
    'wear': (
        'Same finish, different wear categories. Is the difference in asking price worth it?',
        'Before paying more for wear, compare these two listings and inspect the actual item.',
        'The finish stays the same. The wear category and asking price change.',
        'Would you save on wear or pay more? Start with these two price points.',
        'Two wear categories for one finish. Here is the asking price gap today.',
        'A wear label changes the price. Would it change which listing you choose?'),
    'premium_budget': (
        'Budget finish or premium price? Choose the look before checking the gap.',
        'One weapon, two very different price points. Would you spend the extra money?',
        'The expensive option has competition. Which finish would you actually equip?',
        'Would you keep the affordable finish and spend the difference elsewhere?',
        'A bigger price tag does not choose your loadout. Compare these two finishes.',
        'Here is a budget option next to a premium one. Which would you keep?'),
    'popular': (
        'These skins have multiple listings available. Which one belongs in your loadout?',
        'More listings mean more choices to inspect. Which finish catches your attention?',
        'Three available finishes to compare. Supply alone does not tell the whole story.',
        'Look beyond the listing count. Which of these finishes would you equip?',
        'There are choices on the market. Start with these three different finishes.',
        'Plenty of listings, three contenders. Which one would make your shortlist?'),
    'watchlist': (
        'Three affordable finishes to compare. Start with the look, then inspect the asking price.',
        'Build a shortlist before buying. Here are three finishes under the same budget.',
        'A low price is not a forecast. Which of these skins would you inspect first?',
        'Before adding a skin to your watchlist, compare these three current listings.',
        'Three budget candidates, no profit promises. Which one is worth a closer look?',
        'Would any of these make your shortlist? Check the finish, wear, and asking price.')}


def local_script(plan: Plan, history: list[dict], rng: random.Random) -> dict:
    """Write fresh, format-specific commentary using verified facts and local variants."""
    used_hooks = {h.get('hook', '') for h in history[-20:]}
    choices = [x for x in HOOKS[plan.format] if x not in used_hooks]
    if not choices:
        # Least-recently-used opening if someone forces the same format repeatedly.
        last_seen = {x: max((i for i, h in enumerate(history) if h.get('hook') == x), default=-1)
                     for x in HOOKS[plan.format]}
        oldest = min(last_seen.values())
        choices = [x for x in HOOKS[plan.format] if last_seen[x] == oldest]
    hook = rng.choice(choices)
    prices = [x['price'] for x in plan.items]
    cheapest = min(prices)
    running_total = 0.0
    beats = []
    for i, item in enumerate(plan.items):
        price = item['price']
        running_total += price
        gap = abs(price - prices[0])
        if plan.format == 'budget':
            remaining = money(plan.budget - price, plan.currency)
            options = [f'That leaves {remaining} below the budget ceiling.',
                       f'You would still have {remaining} left from this budget.']
            beat = rng.choice(options)
        elif plan.format in {'duel', 'premium_budget'}:
            if i == 0:
                beat = rng.choice(('Remember this finish before seeing the challenger.',
                                   'This is your first option. Keep it in mind.'))
            elif price == prices[0]:
                beat = 'Same asking price. Your choice comes down to the finish.'
            else:
                direction = 'more' if price > prices[0] else 'less'
                beat = f'This costs {money(gap, plan.currency)} {direction} than the first option.'
        elif plan.format == 'loadout':
            beat = f"{plan.labels[i].capitalize()}. Running total: {money(running_total, plan.currency)}."
        elif plan.format == 'wear':
            beat = ('This is the lower asking price in this comparison.' if i == 0 else
                    f'The difference is {money(gap, plan.currency)}. Inspect the actual item before paying more.')
        elif plan.format == 'popular':
            beat = f"{item['quantity']} listings available. That measures supply, not completed sales."
        else:
            beat = ('The lowest asking price in this shortlist.' if price == cheapest else
                    f'{money(price - cheapest, plan.currency)} above the lowest ask in this shortlist.')
        beats.append(beat)
    outros = ('Which finish gets your vote? Tell me in the comments.',
              'Pick your favorite, and tell me what you would change.',
              'Would you equip these? Leave your pick in the comments.',
              'Your loadout, your choice. Which one would you keep?')
    return {'hook': hook, 'beats': beats, 'outro': rng.choice(outros)}


def build_editorial_copy(plan: Plan, script: dict | None, captured: str) -> VideoCopy:
    hook, outro = (script['hook'], script['outro']) if script else (plan.hook, plan.outro)
    lines = [hook]
    for i, item in enumerate(plan.items):
        wear = item['name'].rsplit('(', 1)[-1].rstrip(')')
        detail = script['beats'][i] if script else f"{plan.labels[i].capitalize()}. Which finish fits your style?"
        lines.append(f"{_spoken_name(item['name'])}. {wear}. {money(item['price'], plan.currency)}. {detail}")
    # Always retain the evidence-specific ending, even if the AI writes a CTA.
    lines.append(plan.outro if plan.format in {'loadout', 'wear', 'popular', 'watchlist'} else outro)
    facts = '\n'.join(f"- {x['name']}: {money(x['price'], plan.currency)} ({x['quantity']} listings)"
                      + (f"\n  {x['item_page']}" if x.get('item_page') else '') for x in plan.items)
    description = (f"{plan.title}\n\nSkinport lowest asking prices in {plan.currency}, captured {captured}.\n"
                   f"{facts}\n\nPrices change; asking prices are not completed sales. Fees are excluded. "
                   "Catalog images illustrate the named skin and may not represent an individual listing's float or pattern. "
                   "Picks are subjective, not investment recommendations.\n"
                   "Data: https://skinport.com/\nArt: https://github.com/ByMykel/CSGO-API\n"
                   "#CS2 #CS2Skins #CounterStrike2 #Shorts")
    return VideoCopy(title=plan.title, description=add_promo_link(description), tags=['CS2', 'CS2 skins', 'loadout', 'Shorts'],
                     narration=' '.join(lines), topic=plan.format, featured=plan.items[0],
                     items=plan.items, scene_lines=lines,
                     scene_labels=[plan.title, *plan.labels, 'YOUR TURN'], series='editorial', promo_seconds=3.0)


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


def run(requested='auto', plan_only=False) -> Path:
    from .config import settings, validate_settings
    from .media import _skin_catalog, render_video
    from .providers.skinport import SkinportProvider
    from .youtube import upload_video
    validate_settings()
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
    script = local_script(plan, history, rng)
    copy = build_editorial_copy(plan, script, captured)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(3).hex()
    stem = settings.output_dir / f'editorial-{stamp}'
    metadata = {'captured_at': captured, 'plan': asdict(plan), 'fingerprint': plan.fingerprint,
                'script_source': 'local format writer with verified market facts',
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
    metadata.update(status='rendered', duration_seconds=duration,
                    scene_lines=copy.scene_lines, hook=copy.scene_lines[0])
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
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    log.info('Created %s', run(args.format, args.plan_only))


if __name__ == '__main__':
    main()
