from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)

BASE_URL = "https://skinshotter.com"
BUILD_ID = "pov-github-20261014-v2"
WIDTH, HEIGHT, FPS = 1080, 1920, 30
_WEAR_SUFFIX = re.compile(r"\s*\((Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)$", re.I)
_PREFIX = re.compile(r"^(?:StatTrak™?\s+|Souvenir\s+|★\s*)", re.I)
_CATEGORY = {
    "rifles": "rifles", "pistols": "pistols", "smgs": "smgs", "heavy": "heavy", "knives": "knives",
}


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    if not value:
        raise ValueError(f"Cannot make a Skinshotter URL slug from {value!r}")
    return value


def _base_name(value: str) -> str:
    value = _WEAR_SUFFIX.sub("", value.strip())
    while True:
        cleaned = _PREFIX.sub("", value)
        if cleaned == value:
            break
        value = cleaned
    return value.strip()


def _catalog_entry(market_name: str, catalog: list[dict]) -> dict:
    wanted = _base_name(market_name)
    for entry in catalog:
        candidates = (entry.get("market_hash_name"), entry.get("name"))
        if any(isinstance(candidate, str) and candidate.strip() == market_name.strip() for candidate in candidates):
            return entry
    for entry in catalog:
        candidates = (entry.get("market_hash_name"), entry.get("name"))
        if any(isinstance(candidate, str) and _base_name(candidate) == wanted for candidate in candidates):
            return entry
    raise ValueError(f"Skinshotter route cannot be resolved from the skin catalog: {market_name}")


def supports_weapon_pov(entry: dict) -> bool:
    """Return true only for catalog entries that can form a weapon POV route."""
    weapon = entry.get("weapon") or {}
    pattern = entry.get("pattern") or {}
    category = entry.get("category") or {}
    item_type = entry.get("type") or {}
    weapon_name = weapon.get("name") if isinstance(weapon, dict) else weapon
    pattern_name = pattern.get("name") if isinstance(pattern, dict) else pattern
    category_name = category.get("name") if isinstance(category, dict) else category
    type_name = item_type.get("name") if isinstance(item_type, dict) else item_type
    category_name = str(category_name or "").strip().lower()
    type_name = str(type_name or "").strip().lower()
    market_name = str(entry.get("market_hash_name") or entry.get("name") or "").lower()

    # Gloves are never POV weapon subjects. Check category/type and the market
    # name as a safety net because catalog variants do not always expose the
    # same nested fields (including Hand Wraps, whose name omits "gloves").
    glove_name = any(term in market_name for term in ("gloves", "hand wraps"))
    if "glove" in category_name or "glove" in type_name or glove_name:
        return False

    supported_category = any(key in category_name for key in _CATEGORY)
    return bool(weapon_name and pattern_name and supported_category)


def skin_page_url(market_name: str, catalog: list[dict]) -> str:
    """Resolve a Skinport market name to Skinshotter's canonical weapon page."""
    row = _catalog_entry(market_name, catalog)

    weapon = row.get("weapon") or {}
    pattern = row.get("pattern") or {}
    category = row.get("category") or {}
    weapon_name = weapon.get("name") if isinstance(weapon, dict) else weapon
    finish_name = pattern.get("name") if isinstance(pattern, dict) else pattern
    category_value = category.get("name") if isinstance(category, dict) else category
    category_name = str(category_value or "").lower()
    category_slug = next((slug for key, slug in _CATEGORY.items() if key in category_name), None)
    if not weapon_name or not finish_name or not category_slug:
        raise ValueError(f"Skin catalog entry is missing Skinshotter route fields: {market_name}")

    return f"{BASE_URL}/{category_slug}/{_slug(weapon_name)}/{_slug(finish_name)}"


def skin_wear_value(market_name: str, catalog: list[dict]) -> float:
    """Choose a representative float inside the market's wear tier and skin range."""
    row = _catalog_entry(market_name, catalog)
    suffix = _WEAR_SUFFIX.search(market_name)
    wear = suffix.group(1) if suffix else str((row.get("wear") or {}).get("name") or "")
    bounds = {
        "Factory New": (0.0, 0.07),
        "Minimal Wear": (0.07, 0.15),
        "Field-Tested": (0.15, 0.38),
        "Well-Worn": (0.38, 0.45),
        "Battle-Scarred": (0.45, 1.0),
    }
    tier = next((value for key, value in bounds.items() if key.lower() == wear.lower()), None)
    min_float = float(row.get("min_float", 0.0) or 0.0)
    max_float = float(row.get("max_float", 1.0) or 1.0)
    if not wear:
        return round(max(0.0, min(1.0, min_float)), 5)
    if tier:
        low, high = max(min_float, tier[0]), min(max_float, tier[1])
        if low <= high:
            return round((low + high) / 2, 5)
    return round(max(0.0, min(1.0, (min_float + max_float) / 2)), 5)


def _run_ffmpeg(source: Path, target: Path, seconds: float) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and ffprobe are required for Skinshotter captures")
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-sseof", f"-{seconds:.3f}",
        "-i", str(source),
        "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},setsar=1",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-t", f"{seconds:.3f}", str(target),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    raw = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate:format=duration", "-of", "json", str(target)],
        check=True, capture_output=True, text=True,
    )
    report = json.loads(raw.stdout)
    stream = report["streams"][0]
    duration = float(report["format"]["duration"])
    result = {
        "path": str(target), "width": stream.get("width"), "height": stream.get("height"),
        "fps": stream.get("avg_frame_rate"), "duration_seconds": round(duration, 3),
        "bytes": target.stat().st_size,
    }
    if result["width"] != WIDTH or result["height"] != HEIGHT:
        raise RuntimeError(f"Skinshotter clip has unexpected dimensions: {result['width']}x{result['height']}")
    if duration < seconds - 0.8 or result["bytes"] < 20_000:
        raise RuntimeError(f"Skinshotter clip is incomplete ({duration:.2f}s, {result['bytes']} bytes)")
    return result


async def _capture_pages(pages: list[tuple[str, str, float]], out_dir: Path, seconds: float) -> dict:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "skinshotter-report.json"
    report: dict = {
        "renderer": "Skinshotter WebGPU via Playwright", "captures": [], "result": "started",
        "diagnostic_note": "A failed capture includes the page screenshot, HTML, browser errors, and failed network requests.",
    }

    def save_report() -> None:
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(report_path)

    save_report()
    async with async_playwright() as p:
        headless = os.getenv("SKINSHOTTER_HEADLESS", "true").strip().lower() not in {"0", "false", "no"}
        browser = await p.chromium.launch(headless=headless, args=[
            "--no-sandbox", "--enable-gpu", "--enable-unsafe-webgpu",
            "--enable-features=Vulkan,UseSkiaRenderer", "--use-gl=angle",
            "--use-angle=vulkan", "--disable-vulkan-surface", "--ignore-gpu-blocklist",
        ])
        report["browser_version"] = browser.version
        report["headless"] = headless
        try:
            for index, (market_name, url, wear_value) in enumerate(pages, start=1):
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.hostname != "skinshotter.com":
                    raise ValueError(f"Refusing non-Skinshotter URL: {url}")
                raw_dir = out_dir / f"raw-{index:02d}"
                raw_dir.mkdir(parents=True, exist_ok=True)
                context = await browser.new_context(
                    viewport={"width": WIDTH, "height": HEIGHT},
                    screen={"width": WIDTH, "height": HEIGHT},
                    device_scale_factor=1, reduced_motion="no-preference",
                    record_video_dir=str(raw_dir), record_video_size={"width": WIDTH, "height": HEIGHT},
                )
                page = await context.new_page()
                errors: list[str] = []
                console_errors: list[str] = []
                failed_requests: list[dict] = []
                page.on("pageerror", lambda exc: errors.append(str(exc)[:400]) if len(errors) < 10 else None)
                entry: dict = {"market_name": market_name, "url": url,
                               "representative_wear_float": wear_value, "page_errors": errors,
                               "console_errors": console_errors, "failed_requests": failed_requests}
                report["captures"].append(entry)
                save_report()

                def on_console(message) -> None:
                    if message.type == "error" and len(console_errors) < 30:
                        console_errors.append(message.text[:500])

                def on_request_failed(request) -> None:
                    if len(failed_requests) < 30:
                        failed_requests.append({
                            "url": request.url[:400],
                            "error": str(request.failure or "request failed")[:250],
                        })

                page.on("console", on_console)
                page.on("requestfailed", on_request_failed)
                started = time.monotonic()
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    entry["http_status"] = response.status if response else None
                    entry["response_url"] = response.url if response else page.url
                    if response and response.status >= 400:
                        raise RuntimeError(f"Skinshotter returned HTTP {response.status} for {url}")
                    entry["webgpu"] = await page.evaluate("""async () => {
                      if (!navigator.gpu) return {supported:false, reason:'navigator.gpu missing'};
                      try {
                        const adapter = await Promise.race([
                          navigator.gpu.requestAdapter(),
                          new Promise((_, reject) => setTimeout(() => reject(new Error('adapter timeout')), 10000))
                        ]);
                        if (!adapter) return {supported:false, reason:'requestAdapter returned null'};
                        let info = {};
                        try { info = adapter.info ? {
                          vendor: adapter.info.vendor, architecture: adapter.info.architecture,
                          device: adapter.info.device, description: adapter.info.description
                        } : {}; } catch (_) {}
                        return {supported:true, info};
                      } catch (e) { return {supported:false, reason:String(e)}; }
                    }""")
                    if not entry["webgpu"].get("supported"):
                        raise RuntimeError(f"Chromium WebGPU adapter unavailable: {entry['webgpu'].get('reason')}")
                    # The viewer loads large Source 2 assets after the initial HTML. Give
                    # those requests time to settle, but do not wait indefinitely for
                    # analytics or other long-lived connections.
                    try:
                        await page.wait_for_load_state("networkidle", timeout=12_000)
                    except PlaywrightTimeoutError:
                        pass
                    try:
                        await page.wait_for_function("document.querySelectorAll('canvas').length > 0", timeout=45_000)
                    except PlaywrightTimeoutError as exc:
                        await self_diagnose_page(page, entry, out_dir, index)
                        raise RuntimeError(_no_canvas_reason(entry)) from exc
                    await page.wait_for_timeout(7_000)
                    entry["webgpu"] = await page.evaluate("""async () => {
                      if (!navigator.gpu) return {supported:false, reason:'navigator.gpu missing'};
                      try {
                        const a = await Promise.race([
                          navigator.gpu.requestAdapter(),
                          new Promise((_, reject) => setTimeout(() => reject(new Error('adapter timeout')), 10000))
                        ]);
                        return a ? {supported:true} : {supported:false, reason:'no adapter'};
                      }
                      catch (e) { return {supported:false, reason:String(e)}; }
                    }""")
                    if not entry["webgpu"].get("supported"):
                        raise RuntimeError(f"WebGPU unavailable on this GitHub runner: {entry['webgpu'].get('reason')}")
                    body = await page.locator("body").inner_text()
                    if "No items found" in body and "Copy Inspect Link" not in body:
                        raise RuntimeError(f"Skinshotter did not load the requested item: {market_name}")
                    wear_field = page.get_by_label(re.compile(r"^wear$", re.I))
                    if not await wear_field.count():
                        raise RuntimeError("Skinshotter Wear input was not accessible; refusing to render the wrong exterior")
                    await wear_field.first.evaluate("""(el, value) => {
                      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                      setter.call(el, String(value));
                      el.dispatchEvent(new Event('input', {bubbles:true}));
                      el.dispatchEvent(new Event('change', {bubbles:true}));
                    }""", wear_value)
                    await page.wait_for_timeout(750)
                    wear_text = await page.locator("body").inner_text()
                    shown_wear = re.search(r"\bWear\s+(\d+\.\d+)\s+Pattern\b", wear_text)
                    if not shown_wear or abs(float(shown_wear.group(1)) - wear_value) > 0.003:
                        raise RuntimeError(f"Skinshotter did not apply requested wear float {wear_value:.5f}")
                    entry["applied_wear_float"] = float(shown_wear.group(1))
                    await page.screenshot(path=str(out_dir / f"skinshotter-{index:02d}-before.png"))

                    hide_ui = page.get_by_role("button", name=re.compile(r"hide\s*ui", re.I))
                    if not await hide_ui.count() or not await hide_ui.first.is_visible():
                        hide_ui = page.get_by_text("Hide UI", exact=True)
                    if not await hide_ui.count() or not await hide_ui.first.is_visible():
                        menu = page.get_by_role("button", name=re.compile(r"^menu$", re.I))
                        if await menu.count() and await menu.first.is_visible():
                            await menu.first.click(timeout=3_000)
                            await page.wait_for_timeout(300)
                            hide_ui = page.get_by_text("Hide UI", exact=True)
                    if await hide_ui.count() and await hide_ui.first.is_visible():
                        await hide_ui.first.click(timeout=5_000)
                    else:
                        raise RuntimeError("Skinshotter Hide UI control was not found; refusing to record a cluttered page")
                    canvas = page.locator("canvas").first
                    bounds = await canvas.bounding_box()
                    if not bounds:
                        raise RuntimeError("Skinshotter canvas has no visible bounds")
                    x, y = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
                    await page.mouse.move(x, y)
                    await page.mouse.click(x, y)
                    await page.wait_for_timeout(500)
                    await page.keyboard.press("f")
                    await page.wait_for_timeout(max(1_000, int(seconds * 0.7 * 1_000)))
                    await page.keyboard.press("f")
                    await page.wait_for_timeout(max(500, int(seconds * 0.3 * 1_000)))
                    video = page.video
                    final_frame = out_dir / f"skinshotter-{index:02d}-frame.png"
                    await page.screenshot(path=str(final_frame))
                    from PIL import Image, ImageStat
                    with Image.open(final_frame) as frame_image:
                        stddev = max(ImageStat.Stat(frame_image.convert("RGB")).stddev)
                    entry["frame_channel_stddev"] = round(stddev, 2)
                    if stddev < 8:
                        raise RuntimeError("Skinshotter final frame appears blank or failed to render the 3D scene")
                    await context.close()
                    context = None
                    raw_path = Path(await video.path())
                    output_path = out_dir / f"pov-{index:02d}.mp4"
                    clip = _run_ffmpeg(raw_path, output_path, seconds)
                    entry.update({"clip": clip, "capture_seconds": round(time.monotonic() - started, 2), "result": "passed"})
                    save_report()
                    log.info("Captured Skinshotter POV %s: %s", market_name, output_path)
                except Exception as exc:
                    entry.update({"result": "failed", "error": f"{type(exc).__name__}: {exc}"})
                    if not entry.get("failure_screenshot"):
                        try:
                            await self_diagnose_page(page, entry, out_dir, index)
                        except Exception as diagnostic_error:
                            entry["diagnostic_error"] = f"{type(diagnostic_error).__name__}: {diagnostic_error}"
                    entry["capture_seconds"] = round(time.monotonic() - started, 2)
                    save_report()
                    raise
                finally:
                    if context is not None:
                        await context.close()
        finally:
            await browser.close()
    report["result"] = "passed"
    save_report()
    return report


async def self_diagnose_page(page, entry: dict, out_dir: Path, index: int) -> None:
    """Persist enough evidence to tell a bad route from a blocked/broken viewer."""
    try:
        entry["page_title"] = await page.title()
    except Exception as exc:
        entry["title_error"] = str(exc)[:300]
    entry["final_url"] = page.url
    try:
        entry["canvas_count"] = await page.locator("canvas").count()
    except Exception:
        entry["canvas_count"] = None
    try:
        entry["body_excerpt"] = re.sub(r"\s+", " ", (await page.locator("body").inner_text(timeout=5_000))[:2_000])
    except Exception as exc:
        entry["body_error"] = str(exc)[:300]
    try:
        entry["webgpu"] = await page.evaluate("""async () => {
          if (!navigator.gpu) return {supported:false, reason:'navigator.gpu missing'};
          try {
            const adapter = await Promise.race([
              navigator.gpu.requestAdapter(),
              new Promise((_, reject) => setTimeout(() => reject(new Error('adapter timeout')), 5000))
            ]);
            return adapter ? {supported:true} : {supported:false, reason:'no adapter'};
          } catch (e) { return {supported:false, reason:String(e)}; }
        }""")
    except Exception as exc:
        entry["webgpu"] = {"supported": False, "reason": str(exc)[:300]}
    try:
        screenshot = out_dir / f"skinshotter-{index:02d}-failure.png"
        await page.screenshot(path=str(screenshot), full_page=False, timeout=10_000)
        entry["failure_screenshot"] = str(screenshot)
    except Exception as exc:
        entry["screenshot_error"] = str(exc)[:300]
    try:
        html_path = out_dir / f"skinshotter-{index:02d}-failure.html"
        html_path.write_text((await page.content())[:500_000], encoding="utf-8")
        entry["failure_html"] = str(html_path)
    except Exception as exc:
        entry["html_error"] = str(exc)[:300]


def _no_canvas_reason(entry: dict) -> str:
    status = entry.get("http_status")
    title = entry.get("page_title", "")
    body = entry.get("body_excerpt", "")
    errors = entry.get("page_errors", [])
    failed = entry.get("failed_requests", [])
    if status and status >= 400:
        return f"Skinshotter returned HTTP {status}; see diagnostic screenshot and report"
    if "no items found" in body.lower():
        return "Skinshotter could not resolve this generated weapon/finish route; the selected item is unsupported by its catalog"
    if "captcha" in body.lower() or "access denied" in body.lower() or "verify you are human" in body.lower():
        return "Skinshotter returned an anti-bot/access-check page; GitHub runner is not allowed through"
    if errors:
        return f"Skinshotter page JavaScript failed before creating the viewer: {errors[0]}"
    if failed:
        return f"Skinshotter viewer assets failed to load ({len(failed)} failed requests); see failed_requests in report"
    if title:
        return f"Skinshotter page '{title}' loaded but did not create its 3D canvas; see diagnostic screenshot/report"
    return "Skinshotter did not create its 3D canvas; see diagnostic screenshot/report"


def capture_skin_clips(items: list[dict], catalog: list[dict], out_dir: Path,
                       seconds: float = 5.0) -> list[Path]:
    """Record one automated first-person inspect take per selected market skin."""
    if not 3 <= seconds <= 12:
        raise ValueError("SKINSHOTTER_CLIP_SECONDS must be between 3 and 12")
    pages = [(item["name"], skin_page_url(item["name"], catalog),
              skin_wear_value(item["name"], catalog)) for item in items]
    try:
        report = asyncio.run(_capture_pages(pages, out_dir, seconds))
    except Exception as exc:
        report_path = out_dir / "skinshotter-report.json"
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = {"renderer": "Skinshotter WebGPU via Playwright", "captures": []}
        report.update({"result": "failed", "error": f"{type(exc).__name__}: {exc}"})
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        raise RuntimeError(f"Skinshotter POV capture failed: {type(exc).__name__}: {exc}") from exc
    if report["result"] != "passed" or len(report["captures"]) != len(items):
        raise RuntimeError("Skinshotter did not return a clip for every selected item")
    return [Path(row["clip"]["path"]) for row in report["captures"]]
