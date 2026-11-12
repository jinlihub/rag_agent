"""视觉验证：真机发一问，等回答结束后截取 .timing-line 所在页面。"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://localhost:5174"
OUT = Path(__file__).parent / "ppt_assets" / "timing.png"

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    ctx = b.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=2, locale="zh-CN")
    page = ctx.new_page()
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input[placeholder="用户名"]', "admin")
    page.fill('input[placeholder="密码"]', "admin123")
    page.click("button.submit-btn")
    page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    page.goto(f"{BASE}/chat", wait_until="networkidle")
    page.wait_for_timeout(1200)
    page.locator("textarea:visible").first.fill("招标公告发布的媒介有哪些")
    page.keyboard.press("Enter")
    page.wait_for_selector(".timing-line", timeout=150000)
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT), full_page=True)
    print(f"✓ 已截图 {OUT}")
    b.close()
