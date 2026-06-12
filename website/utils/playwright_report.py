"""
Capture every Streamlit page via a headless Playwright browser and combine
into one PDF.  The result looks exactly like the individual page print-PDFs.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
from pathlib import Path


# ── Page list (title, URL-path) ───────────────────────────────────────────────
_PAGES = [
    ("总结",                  "/"),
    ("策略逻辑",              "/strategy_logic"),
    ("数据与标的池",          "/universe"),
    ("回测方法论",            "/methodology"),
    ("Baseline参数回测结果",  "/baseline_results"),
    ("参数敏感性分析",        "/parameter_sensitivity"),
    ("参数热力图分析",        "/parameter_heatmap"),
    ("蒙特卡洛模拟",          "/monte_carlo"),
    ("Walk-Forward 验证",     "/walk_forward"),
    ("市场环境分析",          "/regime_analysis"),
    ("局限性声明",            "/limitations"),
]


# ── Same CSS that each page's print button already applies ────────────────────
_PRINT_CSS = """
    [data-testid="stSidebar"],
    [data-testid="stSidebarNav"],
    [data-testid="stHeader"],
    [data-testid="stDecoration"],
    [data-testid="stToolbar"],
    [data-testid="stStatusWidget"],
    header, footer,
    .stApp > header { display: none !important; }
    iframe { display: none !important; }
    .main .block-container,
    [data-testid="stMainBlockContainer"] {
        padding-top: 0.5cm !important;
        padding-left: 1cm !important;
        padding-right: 1cm !important;
        max-width: 100% !important;
    }
"""

_INJECT_CSS_JS = f"""
() => {{
    const s = document.createElement('style');
    s.textContent = `{_PRINT_CSS}`;
    document.head.appendChild(s);
}}
"""


# ── Chromium installation ─────────────────────────────────────────────────────
_chromium_installed = False

def _ensure_chromium() -> None:
    """
    Download playwright's bundled chromium binary (no sudo needed).
    System libraries are pre-installed via .streamlit/packages.txt.
    """
    global _chromium_installed
    if _chromium_installed:
        return
    result = subprocess.run(
        # No --with-deps: system libs come from packages.txt (root at build time)
        [sys.executable, "-m", "playwright", "install", "chromium"],
        timeout=300, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "playwright install chromium failed — "
            "check Streamlit Cloud logs for details"
        )
    _chromium_installed = True


# ── Page capture ──────────────────────────────────────────────────────────────
def _capture_all(base_url: str) -> list[bytes]:
    from playwright.sync_api import sync_playwright

    pdfs: list[bytes] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.5,
        )
        page = ctx.new_page()

        for _title, path in _PAGES:
            url = base_url.rstrip("/") + path
            try:
                page.goto(url, wait_until="networkidle", timeout=60_000)
                # Wait for Streamlit's main block container
                page.wait_for_selector(
                    '[data-testid="stMainBlockContainer"]',
                    timeout=30_000,
                )
                # Give charts & spinners time to finish rendering
                page.wait_for_timeout(4_000)
                # Inject print CSS (hides sidebar, header, iframes)
                page.evaluate(_INJECT_CSS_JS)
                page.wait_for_timeout(300)
                pdf = page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "1.5cm", "right": "1.5cm",
                            "bottom": "1.5cm", "left": "1.5cm"},
                )
                pdfs.append(pdf)
            except Exception as exc:
                print(f"[playwright_report] skip {path}: {exc}", file=sys.stderr)

        browser.close()

    return pdfs


def _run_in_thread(fn, *args):
    """Run fn(*args) in a daemon thread; wait up to 5 minutes."""
    result: list = [None]
    error:  list = [None]

    def _worker():
        try:
            result[0] = fn(*args)
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=300)
    if t.is_alive():
        raise TimeoutError("完整报告生成超时（> 5 分钟）")
    if error[0] is not None:
        raise error[0]
    return result[0]


# ── Public API ────────────────────────────────────────────────────────────────
def generate_report() -> bytes:
    """
    Capture all Streamlit pages via playwright and merge into one PDF.
    Connects to the running Streamlit server on localhost.
    """
    from pypdf import PdfWriter, PdfReader

    port = os.environ.get("STREAMLIT_SERVER_PORT", "8501")
    base_url = f"http://localhost:{port}"

    _ensure_chromium()

    page_pdfs = _run_in_thread(_capture_all, base_url)

    if not page_pdfs:
        raise RuntimeError("没有成功捕获任何页面")

    writer = PdfWriter()
    for raw in page_pdfs:
        reader = PdfReader(io.BytesIO(raw))
        for pg in reader.pages:
            writer.add_page(pg)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
