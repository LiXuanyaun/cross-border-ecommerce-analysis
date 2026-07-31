"""Inspect and control the dedicated Chrome/Edge CDP sessions."""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.error import URLError
from urllib.request import urlopen


ENDPOINTS = {
    "chrome": "http://127.0.0.1:9222",
    "edge": "http://127.0.0.1:9223",
}
DEFAULT_URL = "http://localhost:8000"
SIDEBAR_SELECTORS = (
    '[data-testid="stSidebar"]',
    '[data-testid="stHeader"]',
    '[data-testid="stToolbar"]',
    '[data-testid="stSidebarCollapseButton"]',
    '[data-testid="stSidebarCollapsedControl"]',
    '[data-testid="stExpandSidebarButton"]',
    'button[aria-label*="sidebar" i]',
    '[data-testid="stHeader"] button',
)


def debug_status(browser_name: str) -> dict:
    endpoint = ENDPOINTS[browser_name]
    try:
        with urlopen(f"{endpoint}/json/version", timeout=2) as response:
            payload = json.load(response)
        return {
            "browser": browser_name,
            "endpoint": endpoint,
            "ready": bool(payload.get("webSocketDebuggerUrl")),
            "product": payload.get("Browser"),
            "protocol_version": payload.get("Protocol-Version"),
        }
    except (OSError, URLError, ValueError) as exc:
        return {"browser": browser_name, "endpoint": endpoint, "ready": False, "error": str(exc)}


@contextmanager
def connected_page(browser_name: str, url: str | None = None) -> Iterator[object]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed. Run: python -m pip install -r requirements.txt") from exc

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(ENDPOINTS[browser_name])
        if not browser.contexts:
            raise RuntimeError(f"{browser_name} has no browser context")
        context = browser.contexts[0]
        pages = context.pages
        page = next((candidate for candidate in pages if candidate.url.startswith("http://localhost:8000")), None)
        page = page or (pages[0] if pages else context.new_page())
        if url:
            page.goto(url, wait_until="domcontentloaded")
        yield page
    finally:
        # Stopping Playwright disconnects CDP without closing the user's debug browser.
        playwright.stop()


def element_details(page, selector: str) -> list[dict]:
    locator = page.locator(selector)
    details = []
    for index in range(locator.count()):
        item = locator.nth(index)
        details.append(
            {
                "index": index,
                "visible": item.is_visible(),
                "enabled": item.is_enabled(),
                "text": item.inner_text(timeout=1000)[:200],
                "aria_label": item.get_attribute("aria-label"),
                "title": item.get_attribute("title"),
                "testid": item.get_attribute("data-testid"),
                "box": item.bounding_box(),
                "style": item.evaluate(
                    """element => {
                        const style = getComputedStyle(element);
                        return {
                            display: style.display,
                            visibility: style.visibility,
                            opacity: style.opacity,
                            pointerEvents: style.pointerEvents,
                            zIndex: style.zIndex,
                            position: style.position,
                        };
                    }"""
                ),
                "html": item.evaluate("element => element.outerHTML")[0:1000],
            }
        )
    return details


def snapshot(page) -> dict:
    selectors = {selector: element_details(page, selector) for selector in SIDEBAR_SELECTORS}
    try:
        aria = page.locator("body").aria_snapshot(timeout=3000)
    except Exception as exc:  # Browser/Playwright version compatibility fallback.
        aria = f"Unavailable: {exc}"
    return {
        "url": page.url,
        "title": page.title(),
        "viewport": page.viewport_size,
        "selectors": selectors,
        "aria_snapshot": aria[:12000],
        "body_text": page.locator("body").inner_text(timeout=3000)[:4000],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=tuple(ENDPOINTS) + ("all",), default="chrome")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Check the Chromium debug endpoint")

    open_parser = subparsers.add_parser("open", help="Navigate the controlled page")
    open_parser.add_argument("--url", default=DEFAULT_URL)

    snapshot_parser = subparsers.add_parser("snapshot", help="Print URL, accessibility and sidebar DOM state")
    snapshot_parser.add_argument("--url", default=None)

    screenshot_parser = subparsers.add_parser("screenshot", help="Capture a full-page screenshot")
    screenshot_parser.add_argument("--url", default=None)
    screenshot_parser.add_argument("--output", type=Path, required=True)
    screenshot_parser.add_argument("--width", type=int, default=1440)
    screenshot_parser.add_argument("--height", type=int, default=1000)

    click_parser = subparsers.add_parser("click", help="Click one matching DOM element")
    click_parser.add_argument("--selector", required=True)
    click_parser.add_argument("--index", type=int, default=0)
    click_parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    browsers = tuple(ENDPOINTS) if args.browser == "all" else (args.browser,)
    if args.command == "status":
        results = [debug_status(name) for name in browsers]
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0 if all(item["ready"] for item in results) else 1

    if len(browsers) != 1:
        raise SystemExit("open, snapshot, screenshot and click require one --browser")
    browser_name = browsers[0]
    with connected_page(browser_name, getattr(args, "url", None)) as page:
        if args.command == "open":
            result = {"browser": browser_name, "url": page.url, "title": page.title()}
        elif args.command == "snapshot":
            result = snapshot(page)
        elif args.command == "screenshot":
            page.set_viewport_size({"width": args.width, "height": args.height})
            args.output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.output), full_page=True)
            result = {"browser": browser_name, "url": page.url, "output": str(args.output.resolve())}
        else:
            locator = page.locator(args.selector).nth(args.index)
            locator.click(force=args.force)
            result = {"browser": browser_name, "url": page.url, "clicked": args.selector, "index": args.index}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
