"""把生成好的 PPTX 逐页导出 PNG 供排版质检（PowerPoint COM，备选 WPS）。

用法: uv run --with pywin32 python scripts/preview_ppt.py
产出: scripts/ppt_assets/preview/s01.png ... s15.png
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PPTX = Path(r"D:\rag_agent\docs\产品设计与技术架构.pptx")
DEST = Path(__file__).parent / "ppt_assets" / "preview"


def export(progid: str) -> int:
    import win32com.client

    app = win32com.client.Dispatch(progid)
    # Open(FileName, ReadOnly=msoTrue, Untitled=msoFalse, WithWindow=msoFalse)
    pres = app.Presentations.Open(str(PPTX), -1, 0, 0)
    try:
        n = pres.Slides.Count
        for i in range(1, n + 1):
            pres.Slides.Item(i).Export(str(DEST / f"s{i:02d}.png"), "PNG", 1440, 810)
        return n
    finally:
        pres.Close()
        app.Quit()


def main() -> None:
    DEST.mkdir(exist_ok=True)
    for progid in ("PowerPoint.Application", "KWPP.Application"):
        try:
            n = export(progid)
        except Exception as e:
            print(f"· {progid} 不可用: {e}")
            continue
        print(f"✓ {progid} 导出 {n} 页预览 → {DEST}")
        return
    print("× 本机没有 PowerPoint / WPS，跳过视觉质检")


if __name__ == "__main__":
    main()
