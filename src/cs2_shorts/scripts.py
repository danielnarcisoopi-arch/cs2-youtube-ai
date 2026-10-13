from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class VideoCopy:
    title: str
    description: str
    tags: list[str]
    narration: str
    topic: str
    featured: dict[str, Any]
    hook_variant: str = "market_move"


def _money(value: float | int | None, currency: str) -> str:
    return f"{currency} {value:,.2f}" if value is not None else "unavailable"


def _hook(topic: str, item: dict[str, Any], currency: str, variant: str) -> tuple[str, str, str]:
    """Build one of two data-bound openings, then reveal the skin after the hook."""
    name = item["name"]
    change = item.get("change_24h_pct")
    weekly = item.get("change_7d_pct")
    average = item.get("avg_sale_24h")
    low = item.get("min_sale_24h")
    high = item.get("max_sale_24h")
    spread = item.get("volatility_pct")
    price = item.get("price")
    gap = ((price / average) - 1) * 100 if price is not None and average and average > 0 else None

    if topic == "gainers":
        hook = (f"A tracked CS2 skin is up {change:+.1f} percent in 24 hours. "
                "Are recent sales keeping pace?" if change is not None else
                "One CS2 price move is drawing attention. Here is the evidence.")
        reveal = f"The item is {name}."
        takeaway = f"Reported sales were {item.get('volume_24h', 0):,} in 24 hours."
    elif topic == "losers":
        hook = (f"A tracked CS2 skin fell {abs(change):.1f} percent in 24 hours. "
                "How active was the market?"
                if change is not None else "A lower price can hide a quieter market. Let's check the data.")
        reveal = f"The item is {name}."
        takeaway = f"Skinport reports {item.get('volume_24h', 0):,} sales in 24 hours."
    elif topic == "budget":
        hook = f"The listing is {_money(item.get('price'), currency)}. Are buyers actually trading it?"
        reveal = f"Today's active budget pick is {name}."
        takeaway = f"It recorded {item.get('volume_24h', 0):,} reported sales in 24 hours."
    elif topic == "weekly":
        hook = (f"A tracked CS2 skin shifted {weekly:+.1f} percent over the week. "
                "What does the recent sales data say?"
                if weekly is not None else "A full week can tell a different story from one day's price.")
        reveal = f"The item is {name}."
        takeaway = f"The comparison uses the nearest stored snapshot to seven days ago."
    elif topic == "dollar_volume":
        traded = (average or 0) * item.get("volume_24h", 0)
        hook = f"About {_money(traded, currency)} in estimated CS2 sales value. Is the activity broad or concentrated?"
        reveal = f"The item is {name}."
        takeaway = f"Estimated 24-hour traded value is about {_money(traded, currency)}."
    elif topic == "volatility":
        hook = (f"The reported sale prices span {spread:.1f} percent of the average. That's a wide range."
                if spread is not None else "The gap between low and high sale prices can change the story.")
        reveal = f"The item is {name}."
        if low is not None and high is not None:
            takeaway = f"Reported sales ranged from {_money(low, currency)} to {_money(high, currency)}."
        else:
            takeaway = f"The reported 24-hour sales average was {_money(average, currency)}."
    else:
        hook = (f"The lowest ask is {_money(item.get('price'), currency)}, while the reported sale average is "
                f"{_money(average, currency)}. Those numbers tell different stories.")
        reveal = f"Today's CS2 watch item is {name}."
        takeaway = f"It has {item.get('quantity', 0):,} current listings and {item.get('volume_24h', 0):,} reported sales."

    if variant == "price_gap" and gap is not None:
        if gap >= 3:
            hook = (f"The lowest ask is {gap:.1f} percent above the reported 24-hour sale average. "
                    "That gap changes how this move looks.")
        elif gap <= -3:
            hook = (f"The lowest ask sits {abs(gap):.1f} percent below the reported 24-hour sale average. "
                    "Here is what the market is showing.")
        else:
            hook = (f"The lowest ask and reported sale average are within {abs(gap):.1f} percent. "
                    "Now check the broader move.")

    price_line = f"The lowest current listing is {_money(item.get('price'), currency)}."
    if average is not None:
        price_line += f" The reported 24-hour sale average is {_money(average, currency)}."
    cta = "Would you buy, sell, or wait? Comment with your call—and why."
    # Keep one short data caveat instead of repeating disclaimers in the voiceover.
    caveat = "Snapshot data can move quickly; this is market information, not a forecast."
    return hook, reveal, " ".join(part for part in (takeaway, price_line, caveat, cta) if part)


def build_copy(topic: str, rows: list[dict[str, Any]], currency: str, spotlight: bool = False,
               hook_variant: str = "market_move") -> VideoCopy:
    if not rows:
        raise ValueError("No credible rows for script")
    item = rows[0]
    name = item["name"]
    if hook_variant not in {"market_move", "price_gap"}:
        raise ValueError(f"Unsupported hook variant: {hook_variant}")
    hook, reveal, evidence = _hook(topic, item, currency, hook_variant)

    # The first sentence is deliberately data-led and contains no skin name.
    narration = " ".join((hook, reveal, evidence))
    labels = {
        "gainers": "CS2 MARKET ALERT",
        "losers": "CS2 PRICE CHECK",
        "budget": f"CS2 UNDER {currency} 20",
        "weekly": "CS2 WEEKLY SIGNAL",
        "dollar_volume": "CS2 MARKET FLOW",
        "volatility": "CS2 VOLATILITY WATCH",
    }
    title_prefix = labels.get(topic, "CS2 MARKET WATCH")
    # The title can name the item for search; the opening video beat still delays it.
    title = f"{title_prefix}: {name}"
    description = (
        f"A concise CS2 skin market snapshot in {currency}, based on Skinport public market data. "
        "Lowest listing prices are not sale prices. Historical changes compare the current snapshot "
        "with the nearest stored snapshot around the stated period; traded value is an estimate. "
        "Market information only, not a forecast or financial advice.\n\n"
        "Item images: https://github.com/ByMykel/CSGO-API.\n"
        "Fallback narration voice: Piper with LibriTTS-R (CC BY 4.0).\n"
        "Data source: https://skinport.com/\n"
        "#CS2 #CS2Skins #Skinport #SkinTrading #CounterStrike2"
    )
    return VideoCopy(
        title=title[:100],
        description=description,
        tags=["CS2", "CS2 skins", "skin trading", "Skinport", "Counter-Strike 2"],
        narration=narration,
        topic=topic,
        featured=item,
        hook_variant=hook_variant,
    )
