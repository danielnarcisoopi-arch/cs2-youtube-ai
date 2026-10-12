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


def build_copy(topic: str, rows: list[dict[str, Any]], currency: str) -> VideoCopy:
    if not rows:
        raise ValueError("No credible rows for script")
    item = rows[0]
    name = item["name"]
    pct24 = item.get("change_24h_pct")
    pct7 = item.get("change_7d_pct")
    if topic == "gainers":
        title = f"CS2 Market: {name} {pct24:+.1f}% in 24h" if pct24 is not None else f"CS2 Market Watch: {name}"
        hook = f"The {name} is one of today's strongest CS2 market movers, up {abs(pct24):.1f} percent over the last 24 hours." if pct24 is not None else f"The {name} is one of today's strongest CS2 market movers."
        intro = "Here are today's leading CS2 skin gainers, ranked using Skinport listing snapshots."
    elif topic == "losers":
        title = f"CS2 Market Drop: {name} {pct24:.1f}% in 24h" if pct24 is not None else f"CS2 Market Watch: {name}"
        hook = f"The {name} is down {abs(pct24):.1f} percent over the last 24 hours, putting it among today's biggest drops." if pct24 is not None else f"The {name} is among the most watched items today."
        intro = "Here are the biggest tracked CS2 skin price drops from the last 24 hours."
    elif topic == "budget":
        title = f"CS2 Skins Under {currency} 20 to Watch Today"
        hook = f"Looking for CS2 skins under 20 {currency}? The {name} is one of today's most actively traded budget picks."
        intro = "These lower-priced skins have recent Skinport sales activity. A low price alone does not make an item a good investment."
    elif topic == "weekly":
        title = f"CS2 Skin Weekly Movers: {name} {pct7:+.1f}%" if pct7 is not None else f"CS2 Market Watch: {name}"
        hook = f"Over the tracked seven-day window, the {name} moved {pct7:+.1f} percent." if pct7 is not None else f"The {name} is on today's CS2 watchlist."
        intro = "Here are notable CS2 skin moves across our rolling seven-day snapshot window."
    elif topic == "dollar_volume":
        title = f"CS2 Market: Highest Traded Value Today"
        hook = f"The {name} is among the highest traded-value CS2 skins today on Skinport."
        intro = "This ranking estimates traded value from average sale price multiplied by reported 24-hour sales volume."
    elif topic == "volatility":
        title = "CS2 Skins With the Widest Price Range Today"
        hook = f"The {name} had one of the widest reported sale-price ranges in today's Skinport data."
        intro = "This volatility list compares the reported low-to-high sale-price range with each item's average sale price over 24 hours."
    else:
        title = f"CS2 Skins With the Most Market Activity Today"
        hook = f"The {name} is seeing strong activity compared with its current Skinport listing count."
        intro = "This is an activity watchlist, not a price-volatility ranking."
    lines = []
    for i, r in enumerate(rows[:5]):
        line = f"Number {i + 1}: {r['name']}, {currency} {r['price']:.2f}"
        if topic == "volatility" and r.get("volatility_pct") is not None:
            line += f", price range {r['volatility_pct']:.1f} percent of average."
        elif topic == "weekly" and r.get("change_7d_pct") is not None:
            line += f", {r['change_7d_pct']:+.1f} percent in seven days."
        elif r.get("change_24h_pct") is not None:
            line += f", {r['change_24h_pct']:+.1f} percent in 24 hours."
        else:
            line += "."
        lines.append(line)
    narration = " ".join([hook, intro, *lines,
        "Prices and sales can change quickly, and marketplace fees affect what sellers receive.",
        "This is market information, not financial advice. Would you buy, sell, or wait? Comment below."])
    hashtags = "#CS2 #CS2Skins #Skinport #SkinTrading #CounterStrike2"
    description = (f"Market snapshot in {currency}, sourced from Skinport public market data. "
                   "Percentage changes compare our nearest stored snapshots around 24 hours or 7 days apart. "
                   "Budget and volume rankings use reported marketplace sales data. This is informational content, not financial advice.\n\n"
                   f"Data source: https://skinport.com/\n{hashtags}")
    return VideoCopy(title[:100], description, ["CS2", "CS2 skins", "skin trading", "Skinport", "Counter-Strike 2"], narration, topic, item)
