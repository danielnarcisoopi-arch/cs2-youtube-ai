#!/usr/bin/env python3
"""Capture a diagnostic 9:16 Skinshotter clip with Playwright + FFmpeg.

This is intentionally separate from the scheduled publishing pipeline. It
checks whether Skinshotter's WebGPU viewer can render and be recorded on the
GitHub Actions runner before production uses it.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

LOG = logging.getLogger("skinshotter_poc")
WIDTH = 1080
HEIGHT = 1920
DEFAULT_URL = "https://skinshotter.com/rifles/awp/printstream"


def checked_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"skinshotter.com", "www.skinshotter.com"}:
        raise argparse.ArgumentTypeError("URL must be an HTTPS page on skinshotter.com")
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
        "path": str(destination),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "fps": stream.get("avg_frame_rate"),
        "duration_seconds": round(duration, 3),
        "bytes": destination.stat().st_size,
    }
    if result["width"] != WIDTH or result["height"] != HEIGHT:
        raise RuntimeError(f"Unexpected output dimensions: {result['width']}x{result['height']}")
    if duration < seconds - 1.0:
        raise RuntimeError(f"Capture is too short: {duration:.2f}s")
    return result


async def capture(url: str, out_dir: Path, seconds: float, headless: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "skinshotter-report.json"
    screenshot_path = out_dir / "skinshotter-frame.png"
    clean_screenshot_path = out_dir / "skinshotter-clean-frame.png"
    raw_video = out_dir / "skinshotter-raw.webm"
    final_video = out_dir / "skinshotter-vertical.mp4"
    started = time.time()
    report: dict = {
        "url": url,
        "requested_seconds": seconds,
        "viewport": {"width": WIDTH, "height": HEIGHT},
        "browser": None,
        "http_status": None,
        "webgpu": None,
        "canvas_count": 0,
        "page_errors": [],
        "console_errors": [],
        "failed_requests": [],
        "visible_controls": [],
        "actions": [],
        "result": "started",
    }
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:
        report["result"] = "failed"
        report["error"] = "Playwright is not installed; install scripts/requirements-skinshotter.txt"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        raise RuntimeError(report["error"]) from exc

    browser = None
    context = None
    page = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--enable-unsafe-webgpu",
                    "--enable-features=Vulkan",
                    "--use-angle=vulkan",
                    "--disable-vulkan-surface",
                    "--ignore-gpu-blocklist",
                ],
            )
            report["browser"] = browser.version
            context = await browser.new_context(
                viewport={"width": WIDTH, "height": HEIGHT},
                screen={"width": WIDTH, "height": HEIGHT},
                device_scale_factor=1,
                is_mobile=False,
                reduced_motion="no-preference",
                record_video_dir=str(out_dir / "playwright-recordings"),
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
                report["navigation_timeout"] = "Timed out waiting for DOM; checking whether the viewer rendered."

            # Allow the app and Source 2 assets time to load after the document.
            try:
                await page.wait_for_function("document.querySelectorAll('canvas').length > 0", timeout=60_000)
            except PlaywrightTimeoutError:
                pass
            await page.wait_for_timeout(5_000)

            report["title"] = await page.title()
            report["canvas_count"] = await page.locator("canvas").count()
            report["body_excerpt"] = re.sub(r"\s+", " ", (await page.locator("body").inner_text())[:1600])
            report["visible_controls"] = (await page.get_by_role("button").all_text_contents())[:80]
            report["webgpu"] = await page.evaluate("""async () => {
              if (!navigator.gpu) return { supported: false, reason: 'navigator.gpu is missing' };
              try {
                const adapter = await Promise.race([
                  navigator.gpu.requestAdapter(),
                  new Promise((_, reject) => setTimeout(() => reject(new Error('adapter timeout')), 10000))
                ]);
                if (!adapter) return { supported: false, reason: 'requestAdapter returned null' };
                let info = {};
                try { info = adapter.info ? {
                  vendor: adapter.info.vendor, architecture: adapter.info.architecture,
                  device: adapter.info.device, description: adapter.info.description
                } : {}; } catch (_) {}
                return { supported: true, info };
              } catch (e) { return { supported: false, reason: String(e) }; }
            }""")

            # Save diagnostics even when the site rejects the runner or WebGPU is unavailable.
            await page.screenshot(path=str(screenshot_path), full_page=False)
            report["screenshot"] = str(screenshot_path)
            if report["http_status"] and report["http_status"] >= 400:
                raise RuntimeError(f"Skinshotter returned HTTP {report['http_status']}")
            if report["canvas_count"] < 1:
                raise RuntimeError("No 3D canvas rendered; see the screenshot and report artifact")
            if not report["webgpu"].get("supported"):
                raise RuntimeError(f"WebGPU unavailable: {report['webgpu'].get('reason')}")

            # Use the site's own clean-view control if present; otherwise the capture
            # remains useful as a diagnostic and can reveal the actual UI/control labels.
            hide_ui = page.get_by_role("button", name=re.compile(r"hide\s*ui", re.I))
            if await hide_ui.count() and await hide_ui.first.is_visible():
                await hide_ui.first.click(timeout=2_000)
                report["actions"].append("Clicked Skinshotter Hide UI")
            else:
                report["actions"].append("No accessible Hide UI button found")
            await page.screenshot(path=str(clean_screenshot_path), full_page=False)
            report["clean_screenshot"] = str(clean_screenshot_path)

            # Skinshotter advertises CS-style first-person inspection. F is the
            # standard CS inspect key; two spaced presses create two visual beats.
            canvas = page.locator("canvas").first
            bounds = await canvas.bounding_box()
            if bounds:
                await page.mouse.move(bounds["x"] + bounds["width"] / 2,
                                      bounds["y"] + bounds["height"] / 2)
                await page.mouse.click(bounds["x"] + bounds["width"] / 2,
                                       bounds["y"] + bounds["height"] / 2)
            report["actions"].append("Focused the 3D viewer")

            report["recorder"] = "Playwright record_video"
            await page.wait_for_timeout(250)
            await page.keyboard.press("f")
            report["actions"].append("Pressed F to trigger the CS inspect animation")
            await page.wait_for_timeout(max(1_000, int(seconds * 0.45 * 1_000)))
            await page.keyboard.press("f")
            report["actions"].append("Pressed F again for a second inspect beat")
            await page.wait_for_timeout(max(1_000, int(seconds * 0.55 * 1_000)))

            video = page.video
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
            try:
                await context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        report["elapsed_seconds"] = round(time.time() - started, 2)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        LOG.info("Diagnostic report: %s", report_path)


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=checked_url, default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=Path("output/skinshotter-poc"))
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--headed", action="store_true", help="Run Chromium with a visible window")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 30:
        parser.error("--seconds must be between 5 and 30")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        result = await capture(args.url, args.output, args.seconds, headless=not args.headed)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        LOG.exception("Skinshotter proof-of-concept failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
