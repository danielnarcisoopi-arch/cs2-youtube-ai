# CS2 Market Shorts — Architecture Review

Review date: 13 October 2026  
Scope: every file present in the uploaded ZIP (10 files, 48,502 bytes).

## Executive assessment

**Current experience score: 3/10 for retention and premium market-news presentation.** The market-data handling is deliberately cautious, and the workflow has useful automation safeguards. The video experience is still a scripted three-poster slideshow: it announces the item in the opening, relies on generic copy, holds each graphic for roughly a third of the runtime, and uses slow zoom as its only motion. Those choices explain the automated-report feel.

This archive is not a complete runnable repository. `pipeline.py` imports `config`, `providers.skinport`, and `youtube`, but none are included. There is also no `__main__.py`, `pyproject.toml`, package initializer, `.env.example`, or YouTube OAuth helper despite the README describing them. Therefore production behavior in the omitted files, the full upload contract, and a true end-to-end build cannot be verified from this upload. The archive's update note itself instructs the reader to overlay its files onto an existing repo.

## Verified architecture and data flow

1. `.github/workflows/publish.yml` runs on manual dispatch and a four-times-daily UTC schedule. It installs FFmpeg/fonts and Python dependencies, expects the YouTube token secret, downloads Piper voice data, runs `python -m cs2_shorts`, commits `data/market.sqlite3`, and stores MP4/JSON artifacts for 14 days.
2. `pipeline.py` asks `SkinportProvider` for market rows, persists snapshots in SQLite, calculates rankings, avoids spotlight items published in the last 48 hours, and selects one featured item. It builds copy, retrieves that item's recent stored prices, renders an MP4, saves metadata, then optionally uploads and records the published video. The workflow and upload code itself is present only in part; `youtube.py` is absent.
3. `storage.py` stores market snapshots and upload history, then compares current prices with the nearest earlier snapshot within an eight-hour window around 24-hour and seven-day targets.
4. `analytics.py` filters and ranks movers, budget items, traded-value estimates, and a range-based volatility proxy. `choose_spotlight` randomizes among ranked rows while preferring items outside the recent-publication set.
5. `scripts.py` deterministically writes one generic title, hook, informational body, repeated rank-style lines, disclaimer, description, and tags. There is **no prompt, LLM call, or AI script generation** in the supplied code. The perceived AI style comes from the formulaic template and visual repetition, not generated prose from a model.
6. `media.py` tries to match an exact market name to the public ByMykel item catalog, then tries Skinport OpenGraph art, then draws a fallback. Matplotlib creates a price chart; Pillow creates three static 1080×1920 scene cards; Edge-TTS is attempted twice before a Piper neural fallback. FFmpeg loops each card, applies a slow zoom, concatenates the three scenes, burns approximate sentence-weighted SRT captions, normalizes audio, and probes output dimensions/duration.
7. `tests/test_analytics.py` tests ranking and random-item behavior only. There are no tests for copy validity, captions, scene timing, renderer filters, fallback art, audio, or pipeline/upload integration.

## Why the output looks automated

- **The hook spends the first seconds naming the item.** In each spotlight topic, the item name appears in narration immediately and is rendered on scene one. There is no open loop, surprising metric, or delayed reveal.
- **Only three static compositions exist.** The full 30–42 seconds are divided between three cards; each is a static Pillow image with a mild zoom. There are no 2-second visual beats, ticker updates, chart drawing, number rollups, price markers, or transitions beyond hard cuts.
- **Every video follows the same visual grammar.** A rounded dark card, teal brand label, large skin image, and a set of boxes are reused. The index/topic may change but the scene sequence and hierarchy do not.
- **The text is designed like a poster, not broadcast graphics.** Long names, labels, disclaimer text, and metrics compete for space. The same color accents and large all-caps headings flatten the hierarchy. No safe-area or title-fit validation exists.
- **The image is unreliable as the hero.** A failed lookup falls back to text in a box. Even successful image retrieval is a single catalog render, with no controlled crop, depth, or integrated price context.
- **Chart design is static and weakly connected to the story.** The chart is exported as a transparent Matplotlib image, offers only first/last date ticks, and does not identify the selected price observation or animate the move. Sparse history becomes generic placeholder text.
- **Narration is a ranking readout.** Openings such as “The [skin] is among today's tracked gainers” sound generated; the script then reads listing/sales facts and closes with a repeated generic question. It does not build tension or make the comment prompt specific to the actual data.
- **Captions are approximate.** Sentence text is split into up to nine-word chunks and timed only by word count across the total audio duration. The captions are not aligned to actual speech. Font size, contrast, line width, and active-word emphasis are fixed.
- **Narration duration is normalized by changing playback speed.** `atempo` makes the audio fit a 32–42 second target. That can make otherwise acceptable voices sound unnatural, especially for short scripts.
- **No measured retention loop exists.** The project does not capture view duration, viewed-vs-swiped, completion, comments, or topic-level performance. Random selection avoids recent items but does not learn which story structures retain viewers.
- **Market-data limitations are not surfaced in the visual itself.** A lowest listing price can be mistaken for a sale price or fair value. The prose contains caveats, but the graphics do not persistently label listing vs sales data or show the comparison window.
- **The render is unnecessarily expensive.** Each of three 1080×1920 backgrounds is painted pixel-by-pixel in Python. It then loops images into FFmpeg and uses a global `zoompan`; the primary motion is a slow scale change and not content-aware.

## Bottlenecks by impact

1. **Opening retention:** immediate skin-name reveal, generic declarative hook, no visible unresolved question.
2. **Pacing / visual refresh:** only three cards for a 30–42 second runtime; changes are much slower than the requested two-second cadence.
3. **Template originality:** repeated card layout and predictable copy across topics.
4. **Story selection:** selection is randomized across ranks, not prioritized by meaningful, explainable story strength; a random featured row may not represent its category's strongest fact.
5. **Narration quality:** long explanatory phrasing, repeated caveats, no pause/emphasis direction, speed fitting, and fallback quality uncertainty.
6. **Data-to-visual connection:** no live marker, ticker, event beat, or clear distinction between current lowest listing and historical snapshot.
7. **Measurement:** no structured experiments or YouTube Analytics feedback to test hook, length, CTA, and scene pacing.
8. **Build confidence:** missing imported modules prevent a full package run from this archive; current tests cover only analytics.

## Redesign targets for implementation

- Start with a data-led tension line (“This skin's listings just moved 18%—but sales tell a different story”), never the skin name. Only use claims that can be computed from supplied market data; if history is insufficient, use a factual curiosity hook without implying movement.
- Reveal the exact skin after the opening beat; use an opening label, a delayed nameplate, then an evidence sequence and a specific comment choice.
- Replace three posters with a timed sequence of short broadcast beats, refreshing the composition at least every two seconds: opening alert, number reveal, item reveal, listing/sales split, chart window, close/CTA. Use data-driven variations by topic while retaining automation.
- Use a compact market-news system: dark ink canvas, restrained lime/green for positive, red for negative, warm neutral for context, grid/ticker motifs, large tabular figures, persistent source/window labels, and a compact branded bug. Avoid fake live quotes, fake trading terminals, or claims of financial certainty.
- Improve voice pacing and captions without adding an LLM dependency. Keep scripts concise, use robust timing/readability rules, and avoid stretching the whole narration to a fixed duration.
- Make image download and render work bounded and deterministic; cache reusable item artwork and avoid per-pixel Python loops.
- Add tests for script invariants, required beat cadence, safe fallback copy, and renderer command construction. Do not claim retention gains without YouTube Analytics experiments.

## Scope and confidence

Findings about code in this ZIP are direct. Findings about omitted provider, configuration, entry point, OAuth uploader, and the deployed production environment are unknown. The requested goal of doubling average retention is a target, not something source edits alone can guarantee. It requires a baseline and YouTube Analytics measurement, followed by controlled iteration.
