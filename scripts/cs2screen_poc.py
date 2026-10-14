#!/usr/bin/env python3
"""Capture an isolated vertical sample from the official CS2SCREEN viewer.

This proof of concept is deliberately separate from the scheduled publishing
pipeline. It records the public demo or a user-supplied CS2SCREEN viewer URL,
then converts the browser recording to a 1080x1920 MP4 for visual review.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

LOG = logging.getLogger("cs2screen_poc")
WIDTH = 1080
HEIGHT = 1920
# The public demo link published by SteamWebAPI's official viewer page.
DEFAULT_URL = (
    "https://3d.cs2screen.com/?inspectlink="
    "steam%3A%2F%2Frun%2F730%2F%2F%2Bcsgo_econ_action_preview%2520"
    "3A2AFDEC99B99B3B22B13E1AE23C123C0A390280F6B1D2397AEB3B723A6ABB"
    "3952244A32899C03EE&key=pk_4f1f44c6b7c67b7b699d9d39&embed=1"
)


def checked_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "3d.cs2screen.com":
        raise argparse.ArgumentTypeError("URL must be HTTPS on 3d.cs2screen.com")
    return value


def run_ffmpeg(source: Path, destination: Path, seconds: float) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg and ffprobe must be installed")
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-sseof", f"-{seconds}", "-i", str(source), "-t", str(seconds),
        "-vf", f"fps=30,scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
              f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    raw = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate:format=duration", "-of", "json", str(destination)],
        check=True, capture_output=True, text=True,
    )
    probe = json.loads(raw.stdout)
    stream = probe["streams"][0]
    duration = float(probe["format"]["duration"])
    result = {
        "path": str(destination), "width": stream.get("width"),
        "height": stream.get("height"), "fps": stream.get("avg_frame_rate"),
        "duration_seconds": round(duration, 3), "bytes": destination.stat().st_size,
    }
    if result["width"] != WIDTH or result["height"] != HEIGHT:
        raise RuntimeError(f"Unexpected output dimensions: {result['width']}x{result['height']}")
    if duration < seconds - 1.0:
        raise RuntimeError(f"Capture is too short: {duration:.2f}s")
    return result


async def capture(url: str, out_dir: Path, seconds: float) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "cs2screen-report.json"
    screenshot_path = out_dir / "cs2screen-frame.png"
    raw_video = out_dir / "cs2screen-raw.webm"
    final_video = out_dir / "cs2screen-vertical.mp4"
    started = time.time()
    report: dict = {
        "url": url, "requested_seconds": seconds,
        "viewport": {"width": WIDTH, "height": HEIGHT}, "browser": None,
        "http_status": None, "canvas_count": 0, "page_errors": [],
        "console_errors": [], "failed_requests": [], "result": "started",
    }
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:
        report["result"] = "failed"
        report["error"] = "Playwright is not installed"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        raise RuntimeError(report["error"]) from exc

    browser = context = page = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--enable-unsafe-webgpu", "--enable-features=Vulkan",
                      "--use-angle=vulkan", "--disable-vulkan-surface", "--ignore-gpu-blocklist"],
            )
            report["browser"] = browser.version
            context = await browser.new_context(
                viewport={"width": WIDTH, "height": HEIGHT},
                screen={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1,
                reduced_motion="no-preference", record_video_dir=str(out_dir / "recordings"),
                record_video_size={"width": WIDTH, "height": HEIGHT},
            )
            page = await context.new_page()
            page.on("pageerror", lambda exc: report["page_errors"].append(str(exc)[:500]))
            page.on("console", lambda msg: report["console_errors"].append(msg.text[:500])
                    if msg.type == "error" and len(report["console_errors"]) < 30 else None)
            page.on("requestfailed", lambda req: report["failed_requests"].append(
                {"url": req.url[:300], "error": (req.failure or "")[:200]})
                if len(report["failed_requests"]) < 30 else None)

            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                report["http_status"] = response.status if response else None
            except PlaywrightTimeoutError:
                report["navigation_timeout"] = "Timed out waiting for DOM; checking viewer render"
            try:
                await page.wait_for_function("document.querySelectorAll('canvas').length > 0", timeout=60_000)
            except PlaywrightTimeoutError:
                pass
            # Allow textures, models and the viewer's initial camera animation to settle.
            await page.wait_for_timeout(7_000)
            report["title"] = await page.title()
            report["canvas_count"] = await page.locator("canvas").count()
            report["body_excerpt"] = re.sub(r"\s+", " ", (await page.locator("body").inner_text())[:1200])
            report["buttons"] = (await page.get_by_role("button").all_text_contents())[:60]
            report["screenshot"] = str(screenshot_path)
            await page.screenshot(path=str(screenshot_path), full_page=False)
            if report["http_status"] and report["http_status"] >= 400:
                raise RuntimeError(f"CS2SCREEN returned HTTP {report['http_status']}")
            if report["canvas_count"] < 1:
                raise RuntimeError("No 3D canvas rendered; inspect screenshot and report")

            # Record the stable viewer for 10 seconds. This test measures whether the
            # hosted renderer can be captured; it does not claim Arena animation support.
            await page.wait_for_timeout(250)
            video = page.video
            await page.wait_for_timeout(int(seconds * 1_000))
            await context.close()
            context = None
            recorded_path = Path(await video.path())
            if recorded_path.exists():
                raw_video.write_bytes(recorded_path.read_bytes())
            await browser.close()
            browser = None

        if not raw_video.exists() or raw_video.stat().st_size < 10_000:
            raise RuntimeError("Playwright did not produce a usable WebM recording")
        report["raw_video"] = {"path": str(raw_video), "bytes": raw_video.stat().st_size}
        report["video"] = run_ffmpeg(raw_video, final_video, seconds)
        report["result"] = "passed"
        return report
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if context is not None:
            try: await context.close()
            except Exception: pass
        if browser is not None:
            try: await browser.close()
            except Exception: pass
        report["elapsed_seconds"] = round(time.time() - started, 2)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        LOG.info("Diagnostic report: %s", report_path)


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=checked_url, default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=Path("output/cs2screen-poc"))
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 30:
        parser.error("--seconds must be between 5 and 30")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        result = await capture(args.url, args.output, args.seconds)
        print(json.dumps(result, indent=2))
        return 0
    except Exception:
        LOG.exception("CS2SCREEN proof-of-concept failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
