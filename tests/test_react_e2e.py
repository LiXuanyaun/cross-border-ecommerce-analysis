import io
import json
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
    "/business/advertising": "多业务专题分析",
    "/business/returns": "多业务专题分析",
    "/business/logistics": "多业务专题分析",
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
        with urlopen(base_url + "/api/v1/business/datasets", timeout=10) as response:
            business_dataset_id = json.load(response)["data"][0]["dataset_id"]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(EDGE), headless=True)
            page = browser.new_page()
            for width, height in VIEWPORTS:
                page.set_viewport_size({"width": width, "height": height})
                for route, heading in ROUTES.items():
                    page.goto(base_url + route, wait_until="domcontentloaded", timeout=60_000)
                    if route != "/data":
                        dataset_select = page.get_by_role("combobox", name="当前数据集")
                        dataset_select.wait_for(state="visible", timeout=60_000)
                        target_dataset = business_dataset_id if route.startswith("/business/") else "demo-all"
                        if dataset_select.input_value() != target_dataset:
                            dataset_select.select_option(target_dataset)
                        page.wait_for_function(
                            """target => document.querySelector('select[aria-label="当前数据集"]')?.value === target""",
                            arg=target_dataset,
                            timeout=60_000,
                        )
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
                    if route.startswith("/business/"):
                        page.get_by_text("演示推算数据", exact=True).first.wait_for(state="visible", timeout=60_000)
                        page.locator("canvas").first.wait_for(state="visible", timeout=60_000)
                        business_layout = page.evaluate("""() => {
                            const pageMain = Array.from(document.querySelectorAll('main')).at(-1);
                            const blocks = Array.from(pageMain ? pageMain.children : [])
                                .map(element => element.getBoundingClientRect())
                                .filter(box => box.width > 0 && box.height > 0);
                            const overlaps = blocks.slice(1).filter((box, index) => box.top < blocks[index].bottom - 1).length;
                            const canvases = Array.from(document.querySelectorAll('canvas'));
                            const nonblank = canvases.some(canvas => {
                                const context = canvas.getContext('2d');
                                if (!context || canvas.width < 20 || canvas.height < 20) return false;
                                const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
                                let painted = 0;
                                for (let index = 3; index < pixels.length; index += 16) {
                                    if (pixels[index] > 0) painted += 1;
                                    if (painted > 100) return true;
                                }
                                return false;
                            });
                            return { overlaps, canvases: canvases.length, nonblank };
                        }""")
                        assert business_layout["overlaps"] == 0, (route, width, business_layout)
                        assert business_layout["canvases"] > 0, (route, width, business_layout)
                        assert business_layout["nonblank"] is True, (route, width, business_layout)
                    screenshot = page.screenshot(full_page=False)
                    assert len(screenshot) > 10_000
                    with Image.open(io.BytesIO(screenshot)) as image:
                        extrema = image.convert("RGB").resize((64, 64)).getextrema()
                    assert any(low != high for low, high in extrema), (route, width)

            # USER periods survive SPA topic changes; recovery returns to fact-bound AUTO.
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto(base_url + "/analytics?topic=market", wait_until="domcontentloaded", timeout=60_000)
            dataset_select = page.get_by_role("combobox", name="当前数据集")
            dataset_select.select_option(business_dataset_id)
            page.get_by_role("heading", name="专题分析", exact=True).wait_for(state="visible", timeout=60_000)
            for topic_id, topic_label in (("market", "市场"), ("product", "商品"), ("customer", "客户"), ("profit", "利润"), ("returns", "退货")):
                page.get_by_role("button", name=topic_label).click()
                page.wait_for_function(
                    "topic => new URL(location.href).searchParams.get('topic') === topic",
                    arg=topic_id,
                    timeout=60_000,
                )
                page.get_by_role("heading", name="本期摘要", exact=True).wait_for(state="visible", timeout=60_000)
            page.get_by_label("开始日期").fill("2030-01-01")
            page.get_by_label("结束日期").fill("2030-12-31")
            page.get_by_text("手动范围", exact=True).wait_for(state="visible", timeout=60_000)
            page.get_by_text("当前选择时期没有订单事实", exact=True).wait_for(state="visible", timeout=60_000)
            assert page.locator("canvas").count() == 0

            page.get_by_role("link", name="多业务分析").click()
            page.get_by_role("heading", name="多业务专题分析", exact=True).wait_for(state="visible", timeout=60_000)
            assert page.get_by_label("开始日期").input_value() == "2030-01-01"
            assert page.get_by_label("结束日期").input_value() == "2030-12-31"
            page.get_by_role("link", name="退款分析").click()
            page.get_by_text("当前选择时期没有该专题事实", exact=True).wait_for(state="visible", timeout=60_000)
            assert page.get_by_label("开始日期").input_value() == "2030-01-01"
            assert page.get_by_label("结束日期").input_value() == "2030-12-31"
            page.get_by_role("button", name="使用可用时期").click()
            page.get_by_text("系统推荐", exact=True).wait_for(state="visible", timeout=60_000)

            # Dataset changes clear stale topic filters before applying the new recommendation.
            page.get_by_role("link", name="专题分析").click()
            page.get_by_role("heading", name="专题分析", exact=True).wait_for(state="visible", timeout=60_000)
            page.get_by_label("搜索明细").fill("stale-filter")
            page.wait_for_function("() => new URL(location.href).searchParams.has('search')", timeout=60_000)
            dataset_select.select_option("demo-all")
            page.wait_for_function("() => !new URL(location.href).searchParams.has('market') && !new URL(location.href).searchParams.has('category') && !new URL(location.href).searchParams.has('search')", timeout=60_000)
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=15)
