from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .promotion import add_promo_link


@dataclass
class VideoCopy:
    title: str
    description: str
    tags: list[str]
    narration: str
    topic: str
    featured: dict[str, Any]
    hook_variant: str = "market_move"
    items: list[dict[str, Any]] = field(default_factory=list)
    scene_lines: list[str] = field(default_factory=list)
    scene_labels: list[str] = field(default_factory=list)
    series: str = "market"


_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _small_number(value: int) -> str:
    if value < 20:
        return _ONES[value]
    if value < 100:
        return _TENS[value // 10] + (f"-{_ONES[value % 10]}" if value % 10 else "")
    if value < 1000:
        return f"{_ONES[value // 100]} hundred" + (f" {_small_number(value % 100)}" if value % 100 else "")
    return str(value)


def _spoken_percent(value: float) -> str:
    rounded = round(value, 1)
    whole = int(abs(rounded))
    decimal = round((abs(rounded) - whole) * 10)
    number = _small_number(whole) + (f" point {_ONES[decimal]}" if decimal else "")
    return f"{number} percent"


def _spoken_name(name: str) -> str:
    name = name.split("(", 1)[0].replace(" | ", " ").strip()
    return name.replace("AK-47", "AK forty-seven").replace("M4A1-S", "M four A one S")


def _market_move(item: dict[str, Any], topic: str, variant: str) -> tuple[str, str, str]:
    change = item.get("change_24h_pct")
    weekly = item.get("change_7d_pct")
    price = item.get("price")
    average = item.get("avg_sale_24h")
    gap = ((price / average) - 1) * 100 if price is not None and average and average > 0 else None
    name = _spoken_name(item["name"])

    if variant == "price_gap" and gap is not None:
        if gap >= 1:
            hook = "The current ask is above recent sales. Here's the gap."
            reveal = f"It's the {name}, listed {_spoken_percent(gap)} higher."
        elif gap <= -1:
            hook = "Recent sales are above the cheapest listing. Here's the gap."
            reveal = f"It's the {name}, listed {_spoken_percent(gap)} lower."
        else:
            hook = "The current ask and recent sales are almost level."
            reveal = f"It's the {name}. The gap is less than one percent."
        cta = "Would you pay the ask or wait?"
    elif topic == "gainers" and change is not None:
        hook = f"A CS2 skin is up {_spoken_percent(change)} in a day. Would you chase the move?"
        reveal = f"This is the {name}."
        cta = "Buy here, or wait for a pullback?"
    elif topic == "losers" and change is not None:
        hook = f"A CS2 skin is down {_spoken_percent(change)} today. Is this a dip or a warning?"
        reveal = f"It's the {name}."
        cta = "Would you buy the dip, or stay out?"
    elif topic == "weekly" and weekly is not None:
        direction = "up" if weekly >= 0 else "down"
        hook = f"This skin is {direction} {_spoken_percent(abs(weekly))} this week. The daily chart can tell a different story."
        reveal = f"We're looking at the {name}."
        cta = "Is this momentum real, or would you wait?"
    elif topic == "budget":
        hook = "A low asking price is only interesting if people are trading it."
        reveal = f"This is the {name}."
        cta = "Would you add it to your loadout?"
    elif topic == "volatility" and item.get("volatility_pct") is not None:
        hook = "Recent sale prices have a wide spread."
        reveal = f"It's the {name}, with a range equal to {_spoken_percent(item['volatility_pct'])} of the average sale."
        cta = "Would you trade that spread, or pass?"
    elif topic == "dollar_volume":
        hook = "There's real activity around this skin. But is the price moving too?"
        reveal = f"It's the {name}, with {item.get('volume_24h', 0)} reported sales in a day."
        cta = "Would you trade it, or watch for now?"
    else:
        hook = "The cheapest listing and completed sales can tell two different stories."
        reveal = f"Today's watch item is the {name}."
        if gap is not None:
            cta = f"The ask is {_spoken_percent(abs(gap))} {'above' if gap >= 0 else 'below'} the recent sale average. Would you buy or wait?"
        elif change is not None:
            cta = f"It's moved {_spoken_percent(change)} in a day. Would you buy or wait?"
        else:
            cta = "What would you do here: buy, sell, or wait?"
    return hook, reveal, cta


def build_copy(topic: str, rows: list[dict[str, Any]], currency: str, spotlight: bool = False,
               hook_variant: str = "market_move") -> VideoCopy:
    if not rows:
        raise ValueError("No credible rows for script")
    if hook_variant not in {"market_move", "price_gap"}:
        raise ValueError(f"Unsupported hook variant: {hook_variant}")
    items = rows[:5]
    item = items[0]
    if spotlight:
        # The pipeline deliberately selects one evidence-backed spotlight and
        # one hook variant. Keep the video a multi-skin showcase, but make the
        # narration tell the featured skin's actual market story. Previously
        # this branch was bypassed for lists, so every production video used
        # the same generic “five skins” opening and ignored its hook variant.
        hook, reveal, cta = _market_move(item, topic, hook_variant)
        narration = " ".join((hook, reveal, cta))
    elif len(items) > 1:
        count = _small_number(len(items))
        hooks = {
            "gainers": f"{count.capitalize()} CS2 skins are moving up today. I'll show the current ask for each one.",
            "losers": f"{count.capitalize()} CS2 skins fell today. I'll show the current ask for each one.",
            "budget": f"{count.capitalize()} affordable CS2 skins with recent market activity. I'll show today's price for each one.",
            "weekly": f"{count.capitalize()} CS2 skins moved this week. Here's today's asking price for each.",
            "dollar_volume": f"{count.capitalize()} CS2 skins with the most reported sales today. Here's the asking price for each.",
            "volatility": f"{count.capitalize()} CS2 skins with wide reported sale ranges. Here's today's asking price for each.",
        }
        intro = hooks.get(topic, f"{count.capitalize()} CS2 skins to watch today. I'll show the current ask for each.")
        narration = f"{intro} Take a close look at each finish. Which one would you equip? Tell me below."
    else:
        hook, reveal, cta = _market_move(item, topic, hook_variant)
        # Three spoken beats, one short thought each. No ticker-like recital of metrics.
        narration = " ".join((hook, reveal, cta))
    name = item["name"]
    labels = {
        "gainers": "Biggest Movers Today", "losers": "Biggest Drops Today", "budget": "Budget Picks",
        "weekly": "Weekly Movers", "dollar_volume": "Most Traded",
        "volatility": "Wide Sale Ranges",
    }
    title = (f"{len(items)} CS2 Skins: {labels.get(topic, 'Market Picks')}"
             if len(items) > 1 else f"{labels.get(topic, 'CS2 MARKET WATCH')}: {name}")
    description = add_promo_link(
        "A quick CS2 skin market shortlist in " + currency + ", based on Skinport public market data. "
        "Lowest listing prices are not sale prices. Historical changes compare the current snapshot "
        "with the nearest stored snapshot around the stated period; traded value is an estimate. "
        "Market information only, not a forecast or financial advice.\n\n"
        "Item images: https://github.com/ByMykel/CSGO-API.\n"
        "Data source: https://skinport.com/\n"
        "#CS2 #CS2Skins #Skinport #SkinTrading #CounterStrike2"
    )
    return VideoCopy(title[:100], description,
                     ["CS2", "CS2 skins", "skin trading", "Skinport", "Counter-Strike 2"],
                     narration, topic, item, hook_variant, items)
