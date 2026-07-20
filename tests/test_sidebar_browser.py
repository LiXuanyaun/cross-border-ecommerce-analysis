import csv
import io
import os
from pathlib import Path
from urllib.request import urlopen

import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright


APP_URL = "http://localhost:8501"
ENDPOINTS = {
    "chrome": "http://127.0.0.1:9222",
    "edge": "http://127.0.0.1:9223",
}
SCREENSHOTS = Path(__file__).resolve().parents[1] / ".cache" / "browser-debug" / "screenshots"
CHART_VIEWS = ["经营总览", "销售分析", "商品分析", "客户分析", "区域市场", "退货与运营"]
VIEWPORTS = [
    {"width": 1440, "height": 1000},
    {"width": 1280, "height": 800},
    {"width": 1024, "height": 768},
    {"width": 393, "height": 851},
]


def endpoint_ready(endpoint: str) -> bool:
    try:
        with urlopen(f"{endpoint}/json/version", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def boxes_overlap(first: dict, second: dict) -> bool:
    return not (
        first["x"] + first["width"] <= second["x"]
        or second["x"] + second["width"] <= first["x"]
        or first["y"] + first["height"] <= second["y"]
        or second["y"] + second["height"] <= first["y"]
    )


def assert_nonblank_screenshot(path: Path) -> None:
    assert path.exists() and path.stat().st_size > 10_000
    with Image.open(path) as image:
        extrema = image.convert("RGB").resize((64, 64)).getextrema()
    assert any(low != high for low, high in extrema)


def plotly_segment_counts(page) -> list[list[object]]:
    return page.locator('[data-testid="stPlotlyChart"]').first.evaluate(
        """element => {
            const plot = element.querySelector('.js-plotly-plot');
            if (!plot || !plot.calcdata) return [];
            return plot.calcdata.flatMap((series, seriesIndex) =>
                series.map(point => [String(plot._fullData[seriesIndex].name ?? point.x), Number(point.y)])
            ).filter(item => Number.isFinite(item[1]))
              .sort((left, right) => left[0].localeCompare(right[0]));
        }"""
    )


def plotly_boundary_violations(page) -> list[dict]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('[data-testid="stPlotlyChart"]')).flatMap((chart, chartIndex) => {
            const bounds = chart.getBoundingClientRect();
            const selectors = ['.gtitle', '.xtitle', '.ytitle', '.legend', '.xtick text', '.ytick text', '.colorbar'];
            return selectors.flatMap(selector => Array.from(chart.querySelectorAll(selector)).map(element => {
                const box = element.getBoundingClientRect();
                const visible = box.width > 0 && box.height > 0;
                const outside = visible && (
                    box.left < bounds.left - 4 || box.right > bounds.right + 4 ||
                    box.top < bounds.top - 4 || box.bottom > bounds.bottom + 4
                );
                return outside ? {chartIndex, selector, text: element.textContent, box, bounds} : null;
            }).filter(Boolean));
        })"""
    )


def open_sidebar(page):
    sidebar = page.locator('[data-testid="stSidebar"]')
    expect(sidebar).to_be_attached(timeout=60_000)
    if sidebar.get_attribute("aria-expanded") == "false":
        page.locator('[data-testid="stExpandSidebarButton"]').click()
        expect(sidebar).to_have_attribute("aria-expanded", "true")
    return sidebar


@pytest.mark.skipif(os.environ.get("BROWSER_E2E") != "1", reason="requires debug browsers")
@pytest.mark.parametrize("browser_name", ["chrome", "edge"])
def test_sidebar_can_collapse_and_expand_five_times_without_overlap(browser_name):
    endpoint = ENDPOINTS[browser_name]
    if not endpoint_ready(endpoint):
        pytest.skip(f"{browser_name} debug endpoint is not running")

    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0]
        pages = context.pages
        page = next((candidate for candidate in pages if candidate.url.startswith(APP_URL)), pages[0])
        page.goto(APP_URL, wait_until="domcontentloaded")
        page.set_viewport_size({"width": 1440, "height": 1000})

        sidebar = page.locator('[data-testid="stSidebar"]')
        expect(sidebar).to_be_attached(timeout=60_000)
        if sidebar.get_attribute("aria-expanded") == "false":
            page.locator('[data-testid="stExpandSidebarButton"]').click()
            expect(sidebar).to_have_attribute("aria-expanded", "true")

        for _ in range(5):
            collapse = page.locator('[data-testid="stSidebarCollapseButton"] button')
            expect(collapse).to_be_visible()
            collapse.click()
            expect(sidebar).to_have_attribute("aria-expanded", "false")

            expand = page.locator('[data-testid="stExpandSidebarButton"]')
            expect(expand).to_be_visible()
            box = expand.bounding_box()
            assert box is not None
            assert box["width"] >= 36 and box["height"] >= 36
            expand.click()
            expect(sidebar).to_have_attribute("aria-expanded", "true")

        desktop_path = SCREENSHOTS / f"{browser_name}-desktop.png"
        page.screenshot(path=str(desktop_path), full_page=True, timeout=60_000)
        assert_nonblank_screenshot(desktop_path)

        page.set_viewport_size({"width": 393, "height": 851})
        expect(sidebar).to_have_attribute("aria-expanded", "false", timeout=10_000)
        expand = page.locator('[data-testid="stExpandSidebarButton"]')
        expect(expand).to_be_visible()
        heading = page.get_by_role("heading", name="经营总览", exact=True)
        expect(heading).to_be_visible()
        expand_box = expand.bounding_box()
        heading_box = heading.bounding_box()
        assert expand_box is not None and heading_box is not None
        assert not boxes_overlap(expand_box, heading_box)

        expand.click()
        expect(sidebar).to_have_attribute("aria-expanded", "true")


@pytest.mark.skipif(os.environ.get("BROWSER_E2E") != "1", reason="requires debug browsers")
@pytest.mark.parametrize("browser_name", ["chrome", "edge"])
def test_customer_detail_switching_keeps_chart_fixed_and_downloads_search(browser_name, tmp_path):
    endpoint = ENDPOINTS[browser_name]
    if not endpoint_ready(endpoint):
        pytest.skip(f"{browser_name} debug endpoint is not running")

    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0]
        pages = context.pages
        page = next((candidate for candidate in pages if candidate.url.startswith(APP_URL)), pages[0])
        page.goto(APP_URL, wait_until="domcontentloaded")
        page.set_viewport_size({"width": 1440, "height": 1000})

        sidebar = page.locator('[data-testid="stSidebar"]')
        expect(sidebar).to_be_attached(timeout=60_000)
        if sidebar.get_attribute("aria-expanded") == "false":
            page.locator('[data-testid="stExpandSidebarButton"]').click()
        page.locator('[data-testid="stSidebar"] label').filter(has_text="客户分析").click()
        expect(page.get_by_role("heading", name="客户分析", exact=True)).to_be_visible(timeout=30_000)
        expect(page.get_by_text("启用自定义分群规则", exact=True)).to_have_count(0)
        expect(page.get_by_role("radiogroup", name="客户类型")).to_be_visible()

        fixed_chart = plotly_segment_counts(page)
        expected = {
            "VIP客户": 1196,
            "高价值客户": 1012,
            "流失风险客户": 1954,
            "普通客户": 3741,
        }
        assert {label: count for label, count in fixed_chart} == expected
        segment_group = page.get_by_role("radiogroup", name="客户类型")
        for segment, count in expected.items():
            segment_group.get_by_role("radio", name=segment, exact=True).click()
            expect(page.get_by_text(f"当前显示：{count:,} 位{segment}。", exact=False)).to_be_visible(timeout=30_000)
            assert plotly_segment_counts(page) == fixed_chart

        segment_group.get_by_role("radio", name="VIP客户", exact=True).click()
        search = page.get_by_role("textbox", name="搜索表格")
        search.fill("C16655")
        search.press("Enter")
        download_button = page.get_by_role("button", name="下载当前客户清单（1人）", exact=False)
        expect(download_button).to_be_visible(timeout=30_000)
        with page.expect_download() as download_info:
            download_button.click()
        download = download_info.value
        assert download.suggested_filename == "客户清单_VIP_2025-09-12.csv"
        download_path = download.path()
        assert download_path is not None
        payload = Path(download_path).read_bytes()
        assert payload.startswith(b"\xef\xbb\xbf")
        rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
        assert len(rows) == 1
        assert rows[0]["客户ID"] == "C16655"
        assert rows[0]["客户分群"] == "VIP客户"

        page.set_viewport_size({"width": 393, "height": 851})
        mobile_path = SCREENSHOTS / f"{browser_name}-customer-pixel-5.png"
        page.screenshot(path=str(mobile_path), full_page=True, timeout=60_000)
        assert_nonblank_screenshot(mobile_path)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


@pytest.mark.skipif(os.environ.get("BROWSER_E2E") != "1", reason="requires debug browsers")
@pytest.mark.parametrize("browser_name", ["chrome", "edge"])
def test_all_dashboard_charts_fit_supported_viewports(browser_name):
    endpoint = ENDPOINTS[browser_name]
    if not endpoint_ready(endpoint):
        pytest.skip(f"{browser_name} debug endpoint is not running")

    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0]
        pages = context.pages
        page = next((candidate for candidate in pages if candidate.url.startswith(APP_URL)), pages[0])
        page.goto(APP_URL, wait_until="domcontentloaded")

        for view in CHART_VIEWS:
            page.set_viewport_size(VIEWPORTS[0])
            sidebar = open_sidebar(page)
            sidebar.locator("label").filter(has_text=view).click()
            expect(page.get_by_role("heading", name=view, exact=True)).to_be_visible(timeout=30_000)
            expect(page.locator('[data-testid="stPlotlyChart"]').first).to_be_visible(timeout=30_000)

            for viewport in VIEWPORTS:
                page.set_viewport_size(viewport)
                page.wait_for_timeout(300)
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
                ), (browser_name, view, viewport)
                assert plotly_boundary_violations(page) == [], (browser_name, view, viewport)

            if view in {"商品分析", "区域市场"}:
                path = SCREENSHOTS / f"{browser_name}-{view}-{VIEWPORTS[-1]['width']}.png"
                page.screenshot(path=str(path), full_page=True, timeout=60_000)
                assert_nonblank_screenshot(path)
