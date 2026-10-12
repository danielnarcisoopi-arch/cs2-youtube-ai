# CS2 Market Shorts

A Python + FFmpeg pipeline that reads live CS2 market data, builds fact-bound rankings, renders vertical videos with Edge-TTS narration, captions and a price chart, and uploads them to YouTube using OAuth.

## What is implemented

- Live catalog prices, listing counts, 24-hour sale volume, and 24-hour/7-day sale aggregates from Skinport's public API.
- Rankings for 24h gainers/losers, 7-day movers, budget items, estimated traded value and a sale-price-range volatility measure.
- Randomized, data-bound single-skin spotlights. Recently published skins are avoided for 48 hours when enough candidates are available, so rerunning the workflow does not keep choosing the same story.
- Stored point-in-time snapshots. Exact 24-hour and 7-day comparison prices are only reported after enough history has been collected. A nearest sample within eight hours of the target is used to tolerate scheduled-run delays.
- One Short per run: 1080x1920 MP4, 30–42 seconds, generated speech, sentence-level captions, three changing scenes (skin hook, market facts, price chart/CTA), and gradual zoom movement in each scene.
- Automated title, description and tags; upload through YouTube Data API OAuth refresh tokens.
- SQLite market history persisted in the Git repository by the workflow; snapshots older than the retention setting are removed.
- Retry handling, HTTP timeouts, 429/5xx retries, error logs, upload switch and rendering checks.

The script generator is deterministic and uses only fetched prices and calculated metrics. It does not call a paid LLM or invent catalysts, trader sentiment, or future returns. This keeps the videos automatic without making unsupported claims. It labels the content as market information, not financial advice.

## Data source and metric limits

The default provider is **Skinport**, because its documented public `/v1/items` and `/v1/sales/history` endpoints provide a full CS2 item feed without an API key. Both endpoints require Brotli, allow 8 requests per 5 minutes and are cached for five minutes. This project makes two calls per run and does not scrape Steam Community Market, CSFloat, Skinport listing pages, or gambling sites for market data.

The current price is the lowest Skinport listing (`min_price`; suggested price is only used when no listing price is returned). Price change compares the current lowest listing with the closest stored lowest-listing snapshot near 24 hours or 7 days earlier. Sales volume and traded-value rankings use Skinport's aggregated sale statistics. “Volatility” is explicitly the 24-hour reported sale-price range divided by its average; it is a range-based proxy, not a statistical realized-volatility series. Cross-market prices and fees are not blended.

Steam Community Market does not provide a documented, stable public API for this complete feed. CSFloat's documented API uses API-key authentication and does not replace Skinport's free full-catalog price-history feed. The provider interface is isolated so additional authorized APIs can be added without changing the renderer or ranking calculations. No private endpoints or bot/CAPTCHA bypass are used.

The featured item's picture is matched by exact market name against the public ByMykel/CSGO-API item catalog. If that catalog or the image is unavailable, the renderer tries the public Skinport item's OpenGraph metadata and then uses a branded fallback. This is best-effort; check current image and game-asset terms before commercial use. Set `MARKET_IMAGE_FETCH=false` to turn image retrieval off.

Narration tries Edge-TTS first. If Microsoft's endpoint rejects the request (for example, HTTP 403), the workflow uses a downloaded Piper neural voice instead of the very robotic eSpeak fallback. The fallback model is `en_US-libritts_r-medium`; its model card identifies the LibriTTS-R dataset under CC BY 4.0, and the generated YouTube description credits it. The initial workflow setup downloads the model into `data/voices`.

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

Requirements: Python 3.11+, FFmpeg/ffprobe, a font installed on the OS, and network access to Skinport, Edge-TTS, the image catalog and Hugging Face for the Piper fallback voice.

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

`pytest -q` tests the ranking filters and historical comparison logic. The renderer probes the final MP4 to enforce portrait dimensions and 30–45 second duration. A production smoke test still requires authorized live API access, Edge-TTS network access, FFmpeg, and a real YouTube OAuth token; the local test suite deliberately does not upload or contact the marketplace.

Monitor Actions failures, Skinport's API docs and rate limits, YouTube quota, and the OAuth consent-screen state. If a source is empty, malformed, throttled, or unavailable, the run fails rather than publishing made-up or stale prices. Edge-TTS is a free online service without an uptime guarantee; it is not an offline TTS engine.
