"""为《产品设计与技术架构.pptx》采集界面截图素材（无头 Edge + Playwright）。

产出 scripts/ppt_assets/：
- login.png  登录/注册页
- chat.png   C 端问答页（恢复一段历史会话，展示流式回答与消息操作）
- admin.png  B 端维护后台问答列表
- logo.png   Kael Mind 品牌标（480px，白底）

用法: uv run --with playwright python scripts/shoot_ppt.py
前置: 前端 5173、后端 8000 已启动。
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "ppt_assets"
BASE = "http://localhost:5174"

# 与 frontend/src/components/BrandLogo.vue 同源（uid 固定，便于独立渲染）
LOGO_SVG = """<svg width="480" height="480" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
<defs><linearGradient id="kmG" x1="7" y1="5" x2="41" y2="43" gradientUnits="userSpaceOnUse">
<stop stop-color="#6AA8FF"/><stop offset="1" stop-color="#3D6EF7"/></linearGradient></defs>
<rect x="2" y="2" width="44" height="44" rx="13" fill="url(#kmG)"/>
<rect x="2.75" y="2.75" width="42.5" height="42.5" rx="12.25" stroke="#FFFFFF" stroke-opacity="0.25" stroke-width="1.5"/>
<path d="M17.2 13.5v21" stroke="#fff" stroke-width="3.6" stroke-linecap="round"/>
<path d="M18.2 24.2 29.8 14.3" stroke="#fff" stroke-width="3.6" stroke-linecap="round"/>
<path d="M18.2 23.8 29.8 33.7" stroke="#fff" stroke-width="3.6" stroke-linecap="round"/>
<circle cx="31.9" cy="13" r="2.5" fill="#fff"/><circle cx="31.9" cy="35" r="2.5" fill="#fff"/>
<path d="m34.1 11.6 3.3-2.4" stroke="#fff" stroke-opacity="0.55" stroke-width="1.4" stroke-linecap="round"/>
<circle cx="39.3" cy="7.9" r="2.1" fill="#fff" fill-opacity="0.92"/></svg>"""


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 900}, device_scale_factor=2, locale="zh-CN"
        )
        page = ctx.new_page()

        # 1) 登录页
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / "login.png"))
        print("✓ login.png")

        # 2) 登录（管理员默认落 B 端 /admin/qa-list）→ 再进 C 端问答页
        page.fill('input[placeholder="用户名"]', "admin")
        page.fill('input[placeholder="密码"]', "admin123")
        page.click("button.submit-btn")
        page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
        page.goto(f"{BASE}/chat", wait_until="networkidle")
        page.wait_for_timeout(1600)

        # 打开历史抽屉并恢复第一段会话（存量 qa_record 有真实回答）
        try:
            page.click("text=历史对话", timeout=5000)
            page.wait_for_timeout(900)
            page.click(".history-item .history-main", timeout=5000)
            page.wait_for_timeout(1500)
        except Exception as e:  # 抽屉不可用就截默认视图
            print(f"· 历史会话恢复跳过: {e}")
        page.screenshot(path=str(OUT / "chat.png"))
        print("✓ chat.png")

        # 3) B 端维护后台
        page.goto(f"{BASE}/admin/qa-list", wait_until="networkidle")
        page.wait_for_timeout(1400)
        page.screenshot(path=str(OUT / "admin.png"))
        print("✓ admin.png")

        # 4) 品牌标
        logo_page = ctx.new_page()
        logo_page.set_content(
            f'<body style="margin:0;background:#fff;display:flex;align-items:center;'
            f'justify-content:center;height:100vh">{LOGO_SVG}</body>'
        )
        logo_page.wait_for_timeout(300)
        logo_page.locator("svg").screenshot(path=str(OUT / "logo.png"))
        print("✓ logo.png")

        browser.close()


if __name__ == "__main__":
    main()
