import io
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
ROUTES = {
    "/": "经营总览",
    "/analytics": "专题分析",
    "/data": "数据中心",
    "/ai": "AI分析师",
}
VIEWPORTS = ((1440, 1000), (393, 851))


def _free_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _wait_for_server(url: str) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise AssertionError("React test server did not become ready")


def test_react_primary_pages_at_desktop_and_393px():
    assert (ROOT / "frontend" / "dist" / "index.html").exists(), "run npm build before browser regression"
    assert EDGE.exists(), "Microsoft Edge is required for the local browser gate"
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "crossborder_api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        base_url = "http://127.0.0.1:{}".format(port)
        _wait_for_server(base_url + "/api/v1/health")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(EDGE), headless=True)
            page = browser.new_page()
            for width, height in VIEWPORTS:
                page.set_viewport_size({"width": width, "height": height})
                for route, heading in ROUTES.items():
                    page.goto(base_url + route, wait_until="domcontentloaded", timeout=60_000)
                    page.get_by_role("heading", name=heading, exact=True).wait_for(state="visible", timeout=60_000)
                    page.wait_for_timeout(300)
                    layout = page.evaluate("""() => ({
                        viewport: document.documentElement.clientWidth,
                        pageWidth: document.documentElement.scrollWidth,
                        overflowingButtons: Array.from(document.querySelectorAll('button')).filter(element => {
                            const style = getComputedStyle(element);
                            const box = element.getBoundingClientRect();
                            const isCommand = element.querySelectorAll('div').length === 0;
                            return isCommand && style.visibility !== 'hidden' && box.width > 0 && element.scrollWidth > element.clientWidth + 2;
                        }).map(element => element.textContent.trim()).filter(Boolean)
                    })""")
                    assert layout["pageWidth"] <= layout["viewport"] + 1, (route, width, layout)
                    assert layout["overflowingButtons"] == [], (route, width, layout["overflowingButtons"])
                    screenshot = page.screenshot(full_page=False)
                    assert len(screenshot) > 10_000
                    with Image.open(io.BytesIO(screenshot)) as image:
                        extrema = image.convert("RGB").resize((64, 64)).getextrema()
                    assert any(low != high for low, high in extrema), (route, width)
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=15)
