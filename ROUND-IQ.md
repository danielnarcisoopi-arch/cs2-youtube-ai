# CS2 Round IQ Shorts

This is a separate daily Shorts workflow for tactical fundamentals. It does not call Skinport or Skinshotter and does not alter the existing market Shorts workflow.

## Content and visuals

- The first episode bank contains 20 individually written round concepts.
- Each narration has a short question-led opening, a situation, an actionable choice, a reason, and a comment prompt.
- Ten vertical keyframes use matching CS2 radar artwork and place markers at named callout anchors. The focus shifts between the real callout points, with a new visual beat about every two seconds; it does not draw a guessed straight line across the map.
- Map radars are fetched from the auto-updated `MurkyYT/cs2-map-icons` mirror of Valve's game assets; normalized callout anchors are fetched from `UsrUnknow/cs2-radar-callouts`. Both are cached under `data/maps`. Map art is Valve property. The callout dots use named location anchors, not player coordinates reconstructed from a match demo.
- Edge neural narration is used first, with the existing local Piper voice as fallback. The soundtrack is generated locally unless a cleared music file is configured.
- Published episodes are tracked in `data/tactics-history.json`; the workflow rotates through the 20 concepts before starting the list again.

## GitHub Actions

The workflow is `.github/workflows/round-iq.yml` and runs once a day at 14:30 UTC. Scheduled runs upload publicly using the existing `YOUTUBE_TOKEN_JSON` repository secret. A manual workflow run defaults to no upload; download its `cs2-round-iq-<run id>` artifact and review the MP4 first. Enable the `upload` input only when you intend to publish that test.

The title is prefixed with `CS2 Round IQ:` so the series is easy to find on the channel. Playlist placement is not automated by the current OAuth upload scope; add the videos to a YouTube playlist manually if desired.

## Local checks

Run `python -m pytest -q tests/test_tactics.py` for the episode bank, history rotation, map/callout coverage, script limits, and frame checks. Render a preview with `UPLOAD_ENABLED=false python -m cs2_shorts.tactics` after installing the project dependencies and FFmpeg. The first render needs outbound access to GitHub raw file hosting to fetch radar PNGs; later local renders reuse the cache.
