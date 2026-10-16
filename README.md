# CS2 Market Shorts

A Python + FFmpeg pipeline that turns verified CS2 skin-market rankings into a clean top-five vertical showcase and uploads through YouTube OAuth.

## What is implemented

- Live catalog prices, listing counts, 24-hour sale volume, and 24-hour/7-day sale aggregates from Skinport's public API.
- Rankings for 24h gainers/losers, 7-day movers, budget items, estimated traded value and a sale-price-range volatility measure.
- Topic selection remains data-driven; the five strongest fresh skins from that ranking are shown in sequence. Recently published skins are avoided for 48 hours when fresh candidates exist.
- Stored point-in-time snapshots. Exact 24-hour and 7-day comparison prices are only reported after enough history has been collected. A nearest sample within eight hours of the target is used to tolerate scheduled-run delays.
- One Short per run: 1080x1920 MP4, short conversational narration, minimal on-screen copy, and a new visual beat about every two seconds.
- Story arc: a short top-five hook, one item per visual beat with its exact name and current listing price, then one specific question for viewers.
- Topic, selected items, and hook variant remain recorded in the run JSON and SQLite publish history.
- Minimal, full-bleed weapon showcases: exact-match skin art, one market point at a time, slow camera movement, and a restrained original music bed. No transcript captions, repeating ticker, grid, dense data panel, or all-screen disclaimer.
- Automated title, description and tags; upload through YouTube Data API OAuth refresh tokens.
- SQLite market history persisted in the Git repository by the workflow; snapshots older than the retention setting are removed.
- Retry handling, HTTP timeouts, 429/5xx retries, error logs, upload switch and rendering checks.

The script generator is deterministic and uses only fetched prices and calculated metrics. It does not call an LLM or invent catalysts, trader sentiment, or future returns. The voice gives a short introduction and CTA instead of reading five names and prices aloud. Skin names and prices appear on their own visual beats.

See [ARCHITECTURE-REPORT.md](ARCHITECTURE-REPORT.md) for the pre-change review, bottlenecks, and scope limitations. This distribution includes the package entry point, project metadata, Skinport provider, configuration, and YouTube OAuth upload module required by the publishing workflow.

## Data source and metric limits

The default provider is **Skinport**, because its documented public `/v1/items` and `/v1/sales/history` endpoints provide a full CS2 item feed without an API key. Both endpoints require Brotli, allow 8 requests per 5 minutes and are cached for five minutes. This project makes two calls per run and does not scrape Steam Community Market, CSFloat, Skinport listing pages, or gambling sites for market data.

The current price is the lowest Skinport listing (`min_price`; suggested price is only used when no listing price is returned). Price change compares the current lowest listing with the closest stored lowest-listing snapshot near 24 hours or 7 days earlier. Sales volume and traded-value rankings use Skinport's aggregated sale statistics. “Volatility” is explicitly the 24-hour reported sale-price range divided by its average; it is a range-based proxy, not a statistical realized-volatility series. Cross-market prices and fees are not blended.

Steam Community Market does not provide a documented, stable public API for this complete feed. CSFloat's documented API uses API-key authentication and does not replace Skinport's free full-catalog price-history feed. The provider interface is isolated so additional authorized APIs can be added without changing the renderer or ranking calculations. No private endpoints or bot/CAPTCHA bypass are used.

Every skin image is matched by exact market name against the public ByMykel/CSGO-API item catalog. Marketplace page previews are not used because they can include extra text and UI. If exact catalog art is unavailable for any selected skin, the render fails instead of publishing an incomplete list. This is best-effort; check current image and game-asset terms before commercial use. Keep `MARKET_IMAGE_FETCH=true` for skin showcases.

Narration uses a short spoken script. Production videos use the selected spotlight's real market hook, then reveal the item; the hook variant is no longer discarded when the visuals include several skins. The default voice is Microsoft Edge neural voice `en-US-AriaNeural` at a normal speaking rate, with local Piper as an automatic outage fallback. You can tune `EDGE_TTS_RATE` and `EDGE_TTS_PITCH`. For a more natural premium voice, set the GitHub Actions secret `ELEVENLABS_API_KEY` and repository variable `ELEVENLABS_VOICE_ID`; when both exist the pipeline uses that voice first and falls back automatically if its request fails. Premium speech is billed by its provider, so the optional integration is off until you configure credentials.

`CS2_MUSIC_PATH` can point at a music file you have rights to use; the pipeline loops it, fades it in and out, and automatically lowers it under narration. Put the track in the repository (for example, `assets/market-bed.mp3`) and set the repository variable to that path. If no track is configured, FFmpeg creates a restrained original two-chord bed with a soft pulse.

The voice output is still synthesized. The premium option gives you a choice of higher-quality voice models, but a genuinely human performance requires recording a person. The project keeps its automatic fallback chain so a temporary voice-service outage does not stop a scheduled upload.

## Directory tree

```text
cs2-shorts/
├── .github/workflows/publish.yml
├── data/                         # SQLite snapshot history, committed by Actions
├── output/                       # Local MP4 and metadata outputs
├── scripts/auth_youtube.py       # One-time OAuth setup
├── src/cs2_shorts/
│   ├── analytics.py
│   ├── config.py
│   ├── media.py
│   ├── pipeline.py
│   ├── providers/skinport.py
│   ├── scripts.py
│   ├── storage.py
│   └── youtube.py
├── tests/
├── .env.example
├── pyproject.toml
└── requirements.txt
```

## Run locally

Requirements: Python 3.11+, FFmpeg/ffprobe, a font installed on the OS, and network access to Skinport, the image catalog, and the configured speech provider. The workflow downloads the Piper fallback model.

```bash
python -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
```

Set `UPLOAD_ENABLED=false` for safe local renders. Run:

```bash
PYTHONPATH=src python -m cs2_shorts
PYTHONPATH=src pytest -q
```

The first run has no historical changes; it still generates a budget, traded-value, or volatility watchlist when there is sufficient sales data. The 24h list becomes usable after roughly a day and the 7-day list after a week. Never commit `.env`, OAuth client files, or token files.

## YouTube OAuth setup (one-time)

1. In Google Cloud, create a project and enable **YouTube Data API v3**. Configure the OAuth consent screen, then create an OAuth client of type **Desktop app**.
2. Download the client JSON as `client_secret.json` in this folder.
3. Run `python scripts/auth_youtube.py`, sign in as the channel owner and authorize the `youtube.upload` scope. This creates `token.json`; keep it private.
4. Copy the complete `token.json` contents into the repository's GitHub Actions secret named `YOUTUBE_TOKEN_JSON`.
5. Delete the local OAuth files after securely storing the secret, then verify that the first video appears with the expected visibility.

YouTube Data API uses user OAuth; service accounts do not work for regular channel uploads. Google may require OAuth verification or quota review depending on the Cloud project and use. The default documented upload quota is 100 `videos.insert` calls/day; this workflow is scheduled for four uploads/day. A successful API upload is not the same as successful public distribution: processing, channel settings, policy review, age restrictions, and visibility can affect availability.

**OAuth must be set up for unattended operation.** If the OAuth audience is `External` and the publishing status stays `Testing`, Google expires the refresh token after seven days for scopes such as YouTube upload. Move the consent screen to `In production` where allowed and complete any Google verification it requires; otherwise expect to re-authorize manually each week. Separately, YouTube's current Videos documentation says uploads from unverified API projects are private until the project passes an audit. Test with one upload and verify its actual visibility before relying on public scheduled posts. The workflow requests `public`, but Google's project restrictions can override that.

## GitHub production setup

1. Push this directory's contents to a GitHub repository (the workflow expects the repository root to be this project).
2. Add the Actions secret `YOUTUBE_TOKEN_JSON`.
3. In **Settings → Actions → General**, allow GitHub Actions to read and write repository contents, because the workflow commits the rolling SQLite history. Avoid branch rules that reject the bot's data commit, or adapt the persistence step to a database service.
4. Review currency, voice, privacy and content settings in `.github/workflows/publish.yml` and `.env.example`.
5. Run **Actions → CS2 market Shorts → Run workflow** once. Check the action log, the uploaded video, and the generated MP4 artifact before leaving the schedule enabled.

GitHub cron uses UTC, not `Europe/Lisbon`; the configured 08:00, 12:00, 16:00 and 20:00 are UTC and will appear one hour later in Portugal during daylight-saving time. Scheduled jobs can be delayed by GitHub. For stable Lisbon wall-clock delivery, use an external scheduler or have a controlled hourly workflow check `Europe/Lisbon` slots.

The history database is kept in Git to avoid relying on expiring Actions caches. This stores public market data only. A repository with strict branch protection or disabled workflow write permissions needs a separate persistent database.

## Test and operational checks

`pytest -q` tests ranking behavior, short hook/reveal scripts, listing/sale wording, and SQLite history migration. The renderer probes the final MP4 to enforce portrait dimensions and a 12–45 second duration. A production smoke test still requires the omitted repository modules, authorized live API access, speech service, FFmpeg, and a real YouTube OAuth token; tests do not upload or contact the marketplace.

## Retention measurement

The redesign is a creative hypothesis, not a measured retention result. Each upload records its hook variant, topic, item, and duration so the video can be joined to YouTube Analytics. Compare viewed-vs-swiped, average view duration, average percentage viewed, completion, comments per view, and shares per view by hook and topic after enough impressions; do not infer a lift from one upload. Keep the current scheduled publishing workflow while collecting the baseline and follow-up metrics.

Monitor Actions failures, Skinport's API docs and rate limits, YouTube quota, and the OAuth consent-screen state. If a source is empty, malformed, throttled, or unavailable, the run fails rather than publishing made-up or stale prices. Edge-TTS is a free online service without an uptime guarantee; it is not an offline TTS engine.

## Automated first-person skin footage (GitHub Actions only)

The scheduled workflow now uses Skinshotter in Chromium on the GitHub-hosted Actions runner, under a virtual X display with Mesa software Vulkan. It resolves each selected Skinport market name against the existing CS2 catalog, opens that skin's canonical Skinshotter page, records a short first-person inspect take with Playwright, and lets FFmpeg add the existing narration, music, market labels, and 9:16 edit. No CS2 game server, local recording, or manually supplied skin URL is used by the production workflow.

`SKINSHOTTER_ENABLED=true` is the production default in `.github/workflows/publish.yml`. Manual runs are strict: a capture failure stops before upload, and the raw WebM, diagnostic screenshots, JSON report, and any completed MP4 clips are kept in the Actions artifact so the cause can be inspected. Scheduled runs have a temporary safety fallback to the existing renderer if POV capture is unavailable; the metadata identifies that fallback and includes the failure. A manual **workflow_dispatch** run does not upload by default; check the generated artifact first. Scheduled runs continue to upload normally. To manually publish a test, explicitly enable the workflow's `upload` input.

The default runner is `ubuntu-latest`, which has no dedicated GPU. The workflow installs Mesa lavapipe, selects its Vulkan ICD explicitly, verifies the adapter, and runs Chromium with a virtual X display so the viewer can present its WebGPU canvas. Chromium's documented headless GPU path requires explicit GPU/Vulkan configuration on Linux; this workflow uses the same Vulkan route and records adapter/browser diagnostics. If WebGPU is unavailable or a frame fails to render, the manual test stops before upload and saves a report and failure screenshot; scheduled publishing retains its configured fallback. For more reliable/faster rendering, set the repository variable `SKINSHOTTER_RUNNER` to the label of a GitHub-hosted GPU larger runner that your organization has configured. GitHub's GPU larger runners require a GitHub Team or Enterprise organization and are billed while used; this is still a GitHub-hosted runner, not a server you maintain.

## Second daily series: CS2 Round IQ

The independent [CS2 Round IQ workflow](.github/workflows/round-iq.yml) publishes one daily Short about tactical decisions. It uses genuine CS2 map radar artwork with markers anchored to named callout locations and narration; it does not depend on Skinshotter, match demo footage, or the Skinport data pipeline. See [ROUND-IQ.md](ROUND-IQ.md) for the manual test steps and publishing details.

## Third daily series: CS2 Playbook 5v5

The separate [CS2 Playbook workflow](.github/workflows/cs2-playbook.yml) animates five attackers and five defenders around CS2 radar callouts, with an entry flash, site hit, and defensive response. It has its own daily slot, concurrency group, manual upload switch, video filename prefix, and `data/plays-history.json`; it does not edit the Round IQ workflow or its `data/tactics-history.json`. The five scenario bank rotates Mirage A, Inferno B, Dust II A, Ancient B, and Anubis B. See [PLAYBOOK-5V5.md](PLAYBOOK-5V5.md) for run and review instructions.

These are illustrative callout-to-callout route animations, not player paths parsed from demos or verified against a map navmesh. The video and YouTube description disclose that they are simulations. Run the workflow manually with `upload` unchecked and review its MP4 artifact before relying on scheduled publishing.

This renderer uses Skinshotter's browser implementation of Source 2 skin shading and first-person viewmodel animations. The public project documents draw, inspect, and fire animations; reload and free walking are not documented as automated controls, so the current production shot is an inspect-focused POV showcase. The wear tier in the Skinport market name is mapped to a representative float within that tier and checked against Skinshotter's displayed value. Skinport's aggregated catalog does not provide an individual listing's exact float or paint seed, so that exact listing cannot be reconstructed. Unsupported catalog mappings or an unapplied wear value fail rather than fabricating a page or silently showing the wrong exterior. The current pipeline calls the public Skinshotter website, so its availability, usage terms, and browser compatibility are external dependencies.

To test the real production path without publishing: open **Actions → CS2 market Shorts → Run workflow**, leave `upload` unchecked, then download the `cs2-short-<run id>` artifact and review the MP4 plus `data/render/skinshotter/skinshotter-report.json`. The test still uses the live market feed and voice service. If GitHub's standard software renderer cannot initialize WebGPU, first check that report; configure `SKINSHOTTER_RUNNER` only if a GitHub-hosted GPU runner is available on the repository's plan.
