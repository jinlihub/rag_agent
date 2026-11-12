"""生成《产品设计与技术架构.pptx》—— Kael Mind 招投标问答机器人产品/架构汇报片。

设计基调：与前端品牌一致（品牌蓝 #3D6EF7 → #6AA8FF），白底、轻卡片、分层配色沿用
docs/组件工作机制.md 的图例（前端蓝 / 应用绿 / Agent 橙 / 客户端紫 / 检索青 / 数据红）。

用法: uv run --with python-pptx python scripts/make_ppt.py
产出: D:/rag_agent/docs/产品设计与技术架构.pptx（16:9，15 页）
素材: scripts/ppt_assets/{logo,chat,admin,login}.png（scripts/shoot_ppt.py 采集）
"""

from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches as In
from pptx.util import Pt

ROOT = Path(__file__).parent.parent
ASSETS = Path(__file__).parent / "ppt_assets"
OUT = ROOT / "docs" / "产品设计与技术架构.pptx"
FONT = "Microsoft YaHei"

# ── 调色板 ────────────────────────────────────────────────────────────────
INK = "17233D"        # 标题主色
BODY = "3D4759"       # 正文
MUTED = "8A94A6"      # 次要
LINE = "E3E9F4"       # 描边
WHITE = "FFFFFF"
BLUE = "3D6EF7"
BLUE_D = "2F56C4"
BLUE_BG = "EAF1FE"
BLUE_BG2 = "F5F8FF"
# 分层配色（与 docs/组件工作机制.md 图例一致）
LAYERS = {
    "fe": ("2F6BD8", "E8F3FF"),
    "api": ("3E9E4F", "F0F9EB"),
    "agent": ("C77E14", "FDF6EC"),
    "client": ("7B61C4", "F3F0FF"),
    "retri": ("199FA8", "E6F7F7"),
    "data": ("D24A4A", "FFF0F0"),
    "ext": ("6B7280", "F5F5F5"),
}


def C(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_)


def _set_ea(run, face: str) -> None:
    """python-pptx 只设 latin 字体，中文需补 a:ea。"""
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", face)


def P(runs, **kw) -> dict:
    """段落构造：runs = [(text, size, hexcolor, bold), ...]"""
    return {"runs": runs, **kw}


def tb(slide, x, y, w, h, paras, anchor=MSO_ANCHOR.TOP, wrap=True):
    box = slide.shapes.add_textbox(In(x), In(y), In(w), In(h))
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = para.get("align", PP_ALIGN.LEFT)
        if "space_before" in para:
            p.space_before = Pt(para["space_before"])
        if "space_after" in para:
            p.space_after = Pt(para["space_after"])
        if "line_spacing" in para:
            p.line_spacing = para["line_spacing"]
        for text, size, color, bold in para["runs"]:
            r = p.add_run()
            r.text = text
            f = r.font
            f.size = Pt(size)
            f.bold = bold
            f.color.rgb = C(color)
            f.name = FONT
            _set_ea(r, FONT)
    return box


def shape(slide, kind, x, y, w, h, fill=None, line=None, line_w=1.0, radius=None):
    shp = slide.shapes.add_shape(kind, In(x), In(y), In(w), In(h))
    if radius is not None:
        try:
            shp.adjustments[0] = radius
        except Exception:
            pass
    if fill:
        shp.fill.solid()
        shp.fill.fore_color.rgb = C(fill)
    else:
        shp.fill.background()
    if line:
        shp.line.color.rgb = C(line)
        shp.line.width = Pt(line_w)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def card(slide, x, y, w, h, fill=WHITE, line=LINE, radius=0.07):
    return shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill, line, 1.0, radius)


def dot(slide, x, y, d, color):
    return shape(slide, MSO_SHAPE.OVAL, x, y, d, d, color)


def arrow_r(slide, x, y, w, h, color="B9C6E4"):
    return shape(slide, MSO_SHAPE.RIGHT_ARROW, x, y, w, h, color)


def arrow_d(slide, x, y, w, h, color="B9C6E4"):
    return shape(slide, MSO_SHAPE.DOWN_ARROW, x, y, w, h, color)


def conn(slide, x1, y1, x2, y2, color="9DB4E8", width=1.4):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, In(x1), In(y1), In(x2), In(y2))
    c.line.color.rgb = C(color)
    c.line.width = Pt(width)
    c.shadow.inherit = False
    ln = c.line._get_or_add_ln()
    ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))
    return c


def chrome(slide, num, title, tag=""):
    """内页公共骨架：标题 + 章节标 + 分隔线 + 页脚。"""
    shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.6, 0.4, 0.10, 0.42, BLUE, radius=0.5)
    tb(slide, 0.84, 0.30, 9.6, 0.62, [P([(title, 24, INK, True)])])
    if tag:
        tb(slide, 9.2, 0.47, 3.53, 0.32, [P([(tag, 10.5, MUTED, False)], align=PP_ALIGN.RIGHT)])
    shape(slide, MSO_SHAPE.RECTANGLE, 0.6, 1.06, 12.13, 0.012, LINE)
    shape(slide, MSO_SHAPE.RECTANGLE, 0.6, 7.09, 12.13, 0.012, LINE)
    tb(slide, 0.6, 7.16, 8.0, 0.26,
       [P([("Kael Mind · 招投标问答机器人 — 产品设计与技术架构", 8.5, MUTED, False)])])
    tb(slide, 11.9, 7.16, 0.83, 0.26,
       [P([(f"{num:02d}", 9, MUTED, False)], align=PP_ALIGN.RIGHT)])
    slide.notes_slide.notes_text_frame.text = title


def label(slide, x, y, text, color=INK, size=12.5):
    tb(slide, x, y, 6.0, 0.32, [P([(text, size, color, True)])])


# ── 幻灯片 ────────────────────────────────────────────────────────────────
prs = Presentation()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
prs.slide_width = In(13.333)
prs.slide_height = In(7.5)
BLANK = prs.slide_layouts[6]


def new_slide(notes=""):
    s = prs.slides.add_slide(BLANK)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


# ═══ S1 封面 ══════════════════════════════════════════════════════════════
s = new_slide("封面。Kael Mind：基于 LLM + Agent + RAG 的招投标领域智能问答系统。")
shape(s, MSO_SHAPE.OVAL, 10.4, -1.8, 4.8, 4.8, BLUE_BG)
shape(s, MSO_SHAPE.OVAL, -1.9, 5.3, 4.0, 4.0, BLUE_BG2)
dot(s, 12.35, 5.75, 0.42, "6AA8FF")
dot(s, 1.15, 1.15, 0.20, "6AA8FF")
logo = ASSETS / "logo.png"
if logo.exists():
    s.shapes.add_picture(str(logo), In(5.99), In(0.92), In(1.35), In(1.35))
tb(s, 0, 2.42, 13.333, 0.95, [P([("Kael Mind", 46, INK, True)], align=PP_ALIGN.CENTER)])
tb(s, 0, 3.38, 13.333, 0.55,
   [P([("招投标问答机器人 · 产品设计与技术架构", 21, BLUE, True)], align=PP_ALIGN.CENTER)])
chips = [("LLM + Agent + RAG", 2.0), ("ReAct 工具循环", 1.55), ("混合检索 · 动态融合", 1.9),
         ("SSE 流式问答", 1.45), ("C 端问答 × B 端维护", 2.0)]
cx = (13.333 - (sum(w for _, w in chips) + 0.25 * (len(chips) - 1))) / 2
for text, w in chips:
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, cx, 4.42, w, 0.44, BLUE_BG, radius=0.5)
    tb(s, cx, 4.50, w, 0.30, [P([(text, 10.5, BLUE_D, True)], align=PP_ALIGN.CENTER)])
    cx += w + 0.25
tb(s, 0, 5.42, 13.333, 0.34,
   [P([("技术栈：FastAPI · Vue 3 · MySQL · PostgreSQL · NumPy 自研混合检索", 11, MUTED, False)],
      align=PP_ALIGN.CENTER)])
tb(s, 0, 5.82, 13.333, 0.32, [P([("2026 年 10 月", 10.5, MUTED, False)], align=PP_ALIGN.CENTER)])

# ═══ S2 项目背景与产品定位 ═══════════════════════════════════════════════
s = new_slide("痛点来自开发说明 §1.1；定位与闭环来自开发文档 §1.2；业务目标 G1–G4。")
chrome(s, 2, "项目背景与产品定位", "产品设计 · 背景")
label(s, 0.6, 1.28, "行业三大痛点")
pains = [
    ("01", "信息不对称", "公告、政策、企业、价格信息分散在各地交易中心与第三方平台"),
    ("02", "检索效率低", "信息数量庞大，人工搜索与筛选耗时费力"),
    ("03", "专业门槛高", "政策法规与招投标流程专业性强，需要专业解答与建议"),
]
for i, (no, t, d) in enumerate(pains):
    y = 1.66 + i * 1.44
    card(s, 0.6, y, 5.75, 1.30)
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 0.6, y, 0.07, 1.30, BLUE, radius=0.5)
    tb(s, 0.88, y + 0.14, 0.62, 0.42, [P([(no, 15, BLUE, True)])])
    tb(s, 1.52, y + 0.16, 4.6, 0.36, [P([(t, 13, INK, True)])])
    tb(s, 1.52, y + 0.56, 4.66, 0.64, [P([(d, 10.5, BODY, False)], line_spacing=1.12)])

card(s, 6.72, 1.66, 6.01, 2.72)
shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 6.72, 1.66, 0.07, 2.72, BLUE, radius=0.5)
tb(s, 7.02, 1.84, 5.4, 0.36, [P([("产品定位", 13.5, INK, True)])])
tb(s, 7.02, 2.28, 5.45, 1.60,
   [P([("面向招投标全链路人员的 PC Web 端智能问答机器人：以自然语言提问，基于招投标数据资产返回结构化、可溯源的回答。", 11, BODY, False)], line_spacing=1.25),
    P([("B 端维护后台对问答质量人工审核，形成 ", 11, BODY, False),
       ("“机器回答 + 人工维护”", 11, BLUE_D, True),
       (" 的质量闭环。", 11, BODY, False)], line_spacing=1.25, space_before=6)])
shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 7.02, 3.86, 2.55, 0.38, BLUE_BG, radius=0.5)
tb(s, 7.02, 3.93, 2.55, 0.26, [P([("C 端 · 对话问答（/chat）", 9.5, BLUE_D, True)], align=PP_ALIGN.CENTER)])
shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 9.72, 3.86, 2.55, 0.38, BLUE_BG, radius=0.5)
tb(s, 9.72, 3.93, 2.55, 0.26, [P([("B 端 · 维护后台（/admin）", 9.5, BLUE_D, True)], align=PP_ALIGN.CENTER)])

label(s, 6.72, 4.62, "业务目标")
goals = [("G1", "招标信息智能获取"), ("G2", "招标疑问智能解答"),
         ("G3", "个性化信息服务（二期）"), ("G4", "数据安全保障")]
for i, (no, t) in enumerate(goals):
    gx = 6.72 + (i % 2) * 3.06
    gy = 4.98 + (i // 2) * 0.62
    card(s, gx, gy, 2.90, 0.50, BLUE_BG2)
    tb(s, gx + 0.16, gy + 0.12, 0.5, 0.28, [P([(no, 10.5, BLUE, True)])])
    tb(s, gx + 0.62, gy + 0.12, 2.3, 0.28, [P([(t, 10.5, BODY, True)])])

card(s, 0.6, 6.10, 12.13, 0.72, BLUE_BG2)
tb(s, 0.9, 6.24, 11.6, 0.46,
   [P([("目标用户（PRD 典型画像）：", 10.5, INK, True),
       ("企业老板（行情洞察）· 采购（厂家与招标范本）· 技术研发（产品参数）· 销售（商机与中标信息）", 10.5, BODY, False)])])

# ═══ S3 产品功能全景 ══════════════════════════════════════════════════════
s = new_slide("C 端六项能力 + B 端维护后台；全部已实现。历史压缩与消息操作为本期新增。")
chrome(s, 3, "产品功能全景", "产品设计 · 功能")
feats = [
    ("流式智能问答", "SSE 逐字渲染，查询阶段实时可见；Markdown 渲染 + DOMPurify 消毒"),
    ("答案可溯源", "参考来源面板：法条 / 政策 / FAQ / 网页；网页来源可点击核验并显示相关性"),
    ("多轮会话", "会话自动恢复 · 历史抽屉（搜索 / 删除 / 一键接续）· 整段对话可回放"),
    ("历史滚动压缩", "长对话自动压缩为要点摘要并落库，多轮追问不“失忆”"),
    ("消息操作与评价", "复制 / 重新生成 / 赞 · 踩；评价写入问答记录，直达后台筛选"),
    ("灵活提问", "图片理解（多模态）· 联网搜索开关 · 作答模型前端下拉切换"),
]
for i, (t, d) in enumerate(feats):
    fx = 0.6 + (i % 3) * 4.11
    fy = 1.32 + (i // 3) * 1.90
    card(s, fx, fy, 3.90, 1.76)
    dot(s, fx + 0.24, fy + 0.26, 0.13, BLUE)
    tb(s, fx + 0.50, fy + 0.16, 3.2, 0.34, [P([(t, 12.5, INK, True)])])
    tb(s, fx + 0.50, fy + 0.56, 3.22, 1.10, [P([(d, 10, BODY, False)], line_spacing=1.2)])

card(s, 0.6, 5.28, 12.13, 1.52, BLUE_BG2)
tb(s, 0.9, 5.44, 11.5, 0.34,
   [P([("B 端 · 维护后台（/admin/qa-list）", 12.5, INK, True),
       ("　问答记录列表 · 六条件组合筛选 · 标记正确 / 编辑 / 不需要维护", 11, BODY, False)])])
tb(s, 0.9, 5.86, 11.5, 0.34,
   [P([("按维护结果 / 结果评价（赞 · 踩）筛选", 10.5, BODY, False),
       ("，优秀回答沉淀为语料，错误回答人工修正 —— 质量运营有抓手。", 10.5, BODY, False)])])
tb(s, 0.9, 6.26, 11.5, 0.34,
   [P([("支撑能力：", 10.5, INK, True),
       ("注册 / 登录（JWT 鉴权，管理员 / 企业用户 / 自然人三类角色）· “发送”按钮数据埋点（PRD 定义）", 10.5, BODY, False)])])

# ═══ S4 核心问答流程 ══════════════════════════════════════════════════════
s = new_slide("一次问答的全链路：提问即落库 → Agent 编排 → 流式作答 → 反馈 → 维护；SSE 五类事件贯穿。")
chrome(s, 4, "核心问答流程", "产品设计 · 交互")
steps = [
    ("提问", "文本 / 图片 · 联网开关", "5489FB"),
    ("提问即落库", "qa_record 先行可追溯", "4478F9"),
    ("Agent 检索编排", "≤3 轮工具循环", "3D6EF7"),
    ("流式作答", "SSE delta 逐 token", "3663E8"),
    ("用户反馈", "赞 / 踩 · 重新生成", "2F58D6"),
    ("后台维护", "标记正确 / 编辑 / 忽略", "2A4EC4"),
]
for i, (t, d, color) in enumerate(steps):
    sx = 0.6 + i * 2.00
    shape(s, MSO_SHAPE.CHEVRON, sx, 1.34, 2.10, 0.86, color)
    tb(s, sx + 0.30, 1.50, 1.72, 0.30, [P([(t, 11.5, WHITE, True)], align=PP_ALIGN.CENTER)])
    tb(s, sx + 0.30, 1.80, 1.72, 0.24, [P([(d, 8, WHITE, False)], align=PP_ALIGN.CENTER)])

card(s, 0.6, 2.52, 12.13, 1.78, BLUE_BG2)
tb(s, 0.9, 2.66, 11.5, 0.32, [P([("一次问答的 SSE 事件流", 12, INK, True)])]
   )
events = [("meta", "问答记录 ID · 模型名"), ("status", "分析 / 工具 / 质量阶段"),
          ("delta", "逐 token 流式渲染"), ("sources", "参考来源（封顶 20）"), ("done", "结束 · 答案回填")]
ex = 1.05
for i, (name, d) in enumerate(events):
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, ex, 3.10, 1.55, 0.44, BLUE, radius=0.5)
    tb(s, ex, 3.18, 1.55, 0.28, [P([(name, 11, WHITE, True)], align=PP_ALIGN.CENTER)])
    tb(s, ex - 0.12, 3.62, 1.79, 0.55, [P([(d, 9, BODY, False)], align=PP_ALIGN.CENTER, line_spacing=1.1)])
    if i < 4:
        tb(s, ex + 1.57, 3.14, 0.42, 0.36, [P([("→", 14, MUTED, True)], align=PP_ALIGN.CENTER)])
    ex += 2.36

card(s, 0.6, 4.62, 5.95, 1.30)
tb(s, 0.9, 4.78, 5.4, 0.32, [P([("质量闭环", 12, INK, True)])])
tb(s, 0.9, 5.14, 5.42, 0.72,
   [P([("用户赞 / 踩写入问答记录；管理员按评价与维护结果筛选，修正错误回答 —— 回答质量可持续运营。", 10, BODY, False)], line_spacing=1.2)])
card(s, 6.78, 4.62, 5.95, 1.30)
tb(s, 7.08, 4.78, 5.4, 0.32, [P([("数据闭环", 12, INK, True)])])
tb(s, 7.08, 5.14, 5.42, 0.72,
   [P([("提问即落库（失败也可追溯）+ “发送”按钮埋点，为统计分析与检索优化提供全量数据依据。", 10, BODY, False)], line_spacing=1.2)])
tb(s, 0.6, 6.14, 12.13, 0.6,
   [P([("失败兜底：", 10.5, INK, True),
       ("检索无果时如实告知并给出调整建议，不编造数据、不引用不存在的来源。", 10.5, BODY, False)])])

# ═══ S5 界面一览 ══════════════════════════════════════════════════════════
s = new_slide("真实运行截图：C 端问答（含来源面板与消息操作）、B 端维护后台、登录页。")
chrome(s, 5, "界面一览", "产品设计 · 界面")

def shot(slide, path, x, y, w, caption, dot_color=BLUE):
    h = w * 9 / 16
    card(slide, x - 0.045, y - 0.045, w + 0.09, h + 0.09, WHITE, LINE)
    slide.shapes.add_picture(str(path), In(x), In(y), In(w), In(h))
    dot(slide, x + 0.02, y + h + 0.10, 0.12, dot_color)
    tb(slide, x + 0.26, y + h + 0.02, w, 0.3, [P([(caption, 10, BODY, True)])])
    return h

shot(s, ASSETS / "chat.png", 0.62, 1.30, 7.45, "C 端问答：流式回答 · 参考来源（法条 / 网页 · 相关性）· 消息操作")
shot(s, ASSETS / "admin.png", 8.36, 1.30, 4.37, "B 端后台：六条件筛选 · 三类维护操作", "3E9E4F")
shot(s, ASSETS / "login.png", 8.36, 4.24, 4.37, "登录 / 注册：JWT 鉴权 · 三类角色", "7B61C4")

# ═══ S6 技术架构总览 ══════════════════════════════════════════════════════
s = new_slide("五层架构 + 外部模型服务；分层配色与 docs/组件工作机制.md 图例一致。")
chrome(s, 6, "技术架构总览", "技术架构 · 全景")
arch = [
    ("fe", "前端层", "Vue 3 + TypeScript + Element Plus + Vite　—　问答页 · 历史抽屉 · 维护后台 · SSE 流式渲染 · DOMPurify 消毒"),
    ("api", "应用层", "FastAPI + Uvicorn　—　auth(JWT) · chat(SSE) · history · models · vision 图片解析 · admin 维护 · tracking 埋点"),
    ("agent", "智能层", "ReAct Agent 工具循环（≤3 轮）· 4 个 Pydantic 工具 · 结果质量关卡 · 提示词守卫 · llm_factory 多供应商接入"),
    ("retri", "检索层", "混合检索：Dense NumPy 余弦 + Sparse BM25（中文 bigram）→ RRF 动态融合 → LLM 重排 · SQL 结构化检索"),
    ("data", "数据层", "MySQL（user_account / qa_record / session_memory / tracking_event）· PostgreSQL（标的物）· 知识库索引 npz + meta.jsonl"),
]
for i, (key, name, desc) in enumerate(arch):
    dark, tint = LAYERS[key]
    y = 1.34 + i * 1.09
    card(s, 0.6, y, 9.35, 0.94, tint)
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 0.6, y, 0.08, 0.94, dark, radius=0.5)
    tb(s, 0.92, y + 0.28, 1.35, 0.4, [P([(name, 14, dark, True)])])
    tb(s, 2.38, y + 0.14, 7.42, 0.68, [P([(desc, 10, BODY, False)], line_spacing=1.18)],
       anchor=MSO_ANCHOR.MIDDLE)
    if i < 4:
        arrow_d(s, 1.42, y + 0.95, 0.26, 0.13, "C4CFE6")

card(s, 10.14, 1.34, 2.59, 2.42, "F7F8FA")
tb(s, 10.36, 1.48, 2.2, 0.3, [P([("智谱开放平台", 11.5, INK, True)])])
for m, d in [("GLM-4.7-FlashX", "最终作答"), ("glm-4.5-air", "工具轮"), ("glm-4.6v-flashx", "图片理解"), ("embedding-3", "向量化")]:
    tb(s, 10.36, 1.86 + [0, 0.42, 0.84, 1.26][["GLM-4.7-FlashX", "glm-4.5-air", "glm-4.6v-flashx", "embedding-3"].index(m)],
       2.2, 0.36, [P([(m, 10, BLUE_D, True), ("　" + d, 9, MUTED, False)])])
card(s, 10.14, 3.92, 2.59, 0.86, "F7F8FA")
tb(s, 10.36, 4.04, 2.2, 0.3, [P([("Tavily", 11.5, INK, True), ("　联网搜索", 9.5, MUTED, False)])])
tb(s, 10.36, 4.36, 2.2, 0.34, [P([("双源必查兜底", 9.5, BODY, False)])])
card(s, 10.14, 4.94, 2.59, 1.49, BLUE_BG, line=BLUE)
tb(s, 10.36, 5.08, 2.2, 1.2,
   [P([("供应商可替换", 10.5, BLUE_D, True)], line_spacing=1.2),
    P([("OpenAI 兼容协议，智谱 / DeepSeek 配置一键切换", 9.5, BODY, False)], line_spacing=1.2, space_before=4)])
tb(s, 0.6, 6.74, 12.13, 0.3,
   [P([("调用链：", 9.5, INK, True),
       ("前端 fetch/POST → FastAPI 路由 → Agent 循环（模型 + 工具）→ 检索层 → 数据层；SSE 事件流原路返回前端。", 9.5, BODY, False)])])

# ═══ S7 ReAct Agent 工具循环 ══════════════════════════════════════════════
s = new_slide("工具轮 glm-4.5-air 只做编排，作答 GLM-4.7-FlashX 只管表达；联网兜底由代码保证。")
chrome(s, 7, "ReAct Agent 工具循环", "技术架构 · Agent")
card(s, 0.6, 1.30, 6.45, 0.72, BLUE_BG2)
tb(s, 0.88, 1.44, 5.95, 0.48,
   [P([("组装上下文：", 10.5, INK, True), ("system（数据覆盖范围 + 规则）+ 压缩摘要 + history + question", 10.5, BODY, False)])])
arrow_d(s, 3.68, 2.06, 0.28, 0.16)

card(s, 0.6, 2.28, 6.45, 2.42, "FFFDF6", "E6C26A")
tb(s, 0.88, 2.42, 5.9, 0.34,
   [P([("ReAct 工具循环", 12.5, "C77E14", True),
       ("　glm-4.5-air · ≤3 轮 · temperature 0.2 · thinking 关", 9.5, MUTED, False)])])
loop = [("① 分析", "已获得什么 / 还缺什么"), ("② 选工具", "信息不足才发起 tool_calls"),
        ("③ 执行", "知识库 / 图谱 / PG / 联网"), ("④ 质检回填", "低分剔除 · 结果 Observe")]
for i, (t, d) in enumerate(loop):
    lx = 0.92 + i * 1.52
    card(s, lx, 2.92, 1.38, 1.06, WHITE, "EAD9A0")
    tb(s, lx + 0.10, 3.04, 1.2, 0.30, [P([(t, 10, "9A6A0A", True)], align=PP_ALIGN.CENTER)])
    tb(s, lx + 0.10, 3.36, 1.2, 0.58, [P([(d, 8.5, BODY, False)], align=PP_ALIGN.CENTER, line_spacing=1.1)])
    if i < 3:
        tb(s, lx + 1.36, 3.24, 0.18, 0.3, [P([("→", 11, "C77E14", True)], align=PP_ALIGN.CENTER)])
tb(s, 0.88, 4.14, 5.9, 0.4,
   [P([("↻ 结果不足时携带质量结论进入下一轮：换关键词 / 换工具 / 换信息源", 9.5, "9A6A0A", True)])])
arrow_d(s, 3.68, 4.74, 0.28, 0.16)
card(s, 0.6, 4.96, 6.45, 0.66, "FFF6E8")
tb(s, 0.88, 5.10, 5.95, 0.4,
   [P([("联网兜底：", 10.5, INK, True), ("开关开启而未联网 → 代码级强制补查 search_web（防模型偷懒）", 10.5, BODY, False)])])
arrow_d(s, 3.68, 5.66, 0.28, 0.16)
card(s, 0.6, 5.88, 6.45, 0.86, "F0F9EB", "9BD39F")
tb(s, 0.88, 6.00, 5.95, 0.66,
   [P([("最终作答：GLM-4.7-FlashX 流式输出", 11, "2E7D3A", True)], line_spacing=1.2),
    P([("收束守卫：禁止编造数据 · 禁止引用不存在的来源", 9.5, BODY, False)], line_spacing=1.1, space_before=2)])

label(s, 7.35, 1.30, "4 个注册工具（Pydantic 参数校验 · Schema 自动生成）")
tools = [
    ("search_bidding_knowledge", "知识库混合检索", "法条 / 政策 / FAQ · scope 裁剪 · 本期新增 Sparse + RRF", "199FA8"),
    ("search_knowledge_graph", "实体关系图谱", "工商 / 中标 / 采购 / 代理 / 违规关系", "7B61C4"),
    ("search_postgresql", "标的物结构化检索", "地域 / 类别 / 时间 / 金额筛选（PG 8790 行）", "2F6BD8"),
    ("search_web", "联网搜索", "Tavily · 按开关裁剪，开启时双源必查", "C77E14"),
]
for i, (name, t, d, color) in enumerate(tools):
    ty = 1.70 + i * 1.22
    card(s, 7.35, ty, 5.38, 1.08)
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 7.35, ty, 0.07, 1.08, color, radius=0.5)
    tb(s, 7.62, ty + 0.10, 5.0, 0.30, [P([(t, 11.5, INK, True), ("　" + name, 9, MUTED, False)])])
    tb(s, 7.62, ty + 0.46, 4.95, 0.54, [P([(d, 9.5, BODY, False)], line_spacing=1.15)])
tb(s, 7.35, 6.62, 5.38, 0.3,
   [P([("工具描述以“适用于…”句式编写，直接决定 ReAct 选工具的准确率", 9, MUTED, False)])])

# ═══ S8 混合检索与动态融合 ════════════════════════════════════════════════
s = new_slide("按查询类型动态调整 RRF k 值与 Dense/Sparse 权重：法规偏关键词，概念偏语义。")
chrome(s, 8, "混合检索与动态融合", "技术架构 · 检索")
card(s, 0.6, 2.18, 1.40, 0.72, BLUE_BG, line=BLUE)
tb(s, 0.6, 2.36, 1.40, 0.36, [P([("用户查询", 10.5, BLUE_D, True)], align=PP_ALIGN.CENTER)])
arrow_r(s, 2.06, 2.38, 0.32, 0.32)
card(s, 2.44, 2.18, 1.80, 0.72, BLUE_BG, line=BLUE)
tb(s, 2.44, 2.30, 1.80, 0.30, [P([("查询类型识别", 10.5, BLUE_D, True)], align=PP_ALIGN.CENTER)])
tb(s, 2.44, 2.58, 1.80, 0.26, [P([("法规 / 概念 / 通用", 8.5, BODY, False)], align=PP_ALIGN.CENTER)])
conn(s, 4.24, 2.40, 4.62, 1.82)
conn(s, 4.24, 2.68, 4.62, 3.26)
card(s, 4.62, 1.36, 2.15, 0.82, "E6F7F7", "2FB8B8")
tb(s, 4.62, 1.46, 2.15, 0.30, [P([("Dense 向量检索", 10.5, "12777D", True)], align=PP_ALIGN.CENTER)])
tb(s, 4.62, 1.76, 2.15, 0.26, [P([("NumPy 余弦 · npz 索引", 8.5, BODY, False)], align=PP_ALIGN.CENTER)])
card(s, 4.62, 2.96, 2.15, 0.82, "E6F7F7", "2FB8B8")
tb(s, 4.62, 3.06, 2.15, 0.30, [P([("Sparse BM25 检索", 10.5, "12777D", True)], align=PP_ALIGN.CENTER)])
tb(s, 4.62, 3.36, 2.15, 0.26, [P([("中文 bigram · 内存索引", 8.5, BODY, False)], align=PP_ALIGN.CENTER)])
conn(s, 6.77, 1.82, 7.22, 2.42)
conn(s, 6.77, 3.26, 7.22, 2.66)
card(s, 7.22, 2.18, 1.75, 0.72, BLUE, line=None)
tb(s, 7.22, 2.30, 1.75, 0.30, [P([("RRF 动态融合", 10.5, WHITE, True)], align=PP_ALIGN.CENTER)])
tb(s, 7.22, 2.58, 1.75, 0.26, [P([("按画像加权去重", 8.5, "DCE7FF", False)], align=PP_ALIGN.CENTER)])
arrow_r(s, 9.03, 2.38, 0.32, 0.32)
card(s, 9.41, 2.18, 1.75, 0.72, BLUE_BG, line=BLUE)
tb(s, 9.41, 2.30, 1.75, 0.30, [P([("LLM 重排（可选）", 10, BLUE_D, True)], align=PP_ALIGN.CENTER)])
tb(s, 9.41, 2.58, 1.75, 0.26, [P([("精排出 Top-K 证据", 8.5, BODY, False)], align=PP_ALIGN.CENTER)])
arrow_r(s, 11.22, 2.38, 0.32, 0.32)
card(s, 11.60, 2.18, 1.13, 0.72, BLUE_BG2, line=LINE)
tb(s, 11.60, 2.36, 1.13, 0.36, [P([("Top-K 证据", 9.5, INK, True)], align=PP_ALIGN.CENTER)])

label(s, 0.6, 4.22, "查询类型画像（_PROFILES：k 值与权重随问题类型动态调整）")
rows = [
    ("查询类型", "RRF k", "Dense 权重", "Sparse 权重", "检索倾向"),
    ("法规类（法条编号 / 专有术语）", "k = 30", "0.4", "0.6", "关键词精准优先，小窗口高置信"),
    ("概念类（流程 / 释义）", "k = 80", "0.7", "0.3", "语义泛化优先，大窗口召回"),
    ("通用类", "k = 60", "0.55", "0.45", "均衡融合"),
]
gfx = s.shapes.add_table(4, 5, In(0.6), In(4.62), In(8.95), In(1.90))
tbl = gfx.table
tbl.first_row = False
tbl.horz_banding = False
for i, w in enumerate([2.75, 1.15, 1.35, 1.35, 2.35]):
    tbl.columns[i].width = In(w)
for r, row in enumerate(rows):
    tbl.rows[r].height = In(0.475)
    for c, val in enumerate(row):
        cell = tbl.cell(r, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = C(BLUE if r == 0 else (WHITE if r % 2 else "F7FAFF"))
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = In(0.10)
        cell.margin_right = In(0.06)
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER if 0 < c < 4 else PP_ALIGN.LEFT
        run = p.add_run()
        run.text = val
        f = run.font
        f.size = Pt(9.5 if r else 10)
        f.bold = (r == 0 or c == 0)
        f.color.rgb = C(WHITE if r == 0 else (INK if c == 0 else BODY))
        f.name = FONT
        _set_ea(run, FONT)

notes8 = [
    ("行号即去重键", "Dense 与 Sparse 共用 meta.jsonl 行号（row）做 RRF 去重 —— 索引行序不可变"),
    ("低分即剔除", "相关性 < 0.35 的条目不进入参考来源；来源列表封顶 20 条"),
]
for i, (t, d) in enumerate(notes8):
    ny = 4.62 + i * 1.00
    card(s, 9.80, ny, 2.93, 0.88, BLUE_BG2)
    tb(s, 10.02, ny + 0.10, 2.5, 0.28, [P([(t, 10.5, BLUE_D, True)])])
    tb(s, 10.02, ny + 0.38, 2.55, 0.46, [P([(d, 8.5, BODY, False)], line_spacing=1.12)])
tb(s, 0.6, 6.68, 8.95, 0.3,
   [P([("为什么动态：法规问题命中法条编号靠字面，概念问题（“什么是单一来源采购”）靠语义 —— 一套固定权重顾此失彼。", 9.5, MUTED, False)])])

# ═══ S9 结果质量关卡 ══════════════════════════════════════════════════════
s = new_slide("每次工具执行后按行数 + 相关性打分；不达标驱动换策略，全程无果则如实告知。")
chrome(s, 9, "结果质量关卡（防幻觉机制）", "技术架构 · 质量")
card(s, 0.6, 1.60, 3.30, 2.30, BLUE_BG, line=BLUE)
tb(s, 0.86, 1.78, 2.8, 0.34, [P([("① 质量评估", 12.5, BLUE_D, True)])])
tb(s, 0.86, 2.20, 2.82, 1.55,
   [P([("每次工具执行后判定：", 10, BODY, False)], line_spacing=1.2),
    P([("行数 + 相关性分数", 10, INK, True)], line_spacing=1.2, space_before=4),
    P([("→ ok / empty / weak / error（阈值 0.35）", 10, BODY, False)], line_spacing=1.2, space_before=4)])
arrow_r(s, 3.98, 2.58, 0.34, 0.34)
branches = [
    ("✓ ok", "进入参考来源面板", "低分条目剔除 · 来源封顶 20 条 · 本地 / 网页来源标注类型与相关性", "2E7D3A", "F0F9EB"),
    ("⚠ empty / weak", "质量结论回填，驱动换策略", "stage=quality 事件同步前端状态条；下一轮换关键词 / 换工具 / 换信息源", "9A6A0A", "FFF6E8"),
    ("✗ error", "异常折叠为 error 字段", "工具异常不中断流程，模型可读取错误信息自纠重试", "C05040", "FFF0F0"),
]
for i, (tag, t, d, color, tint) in enumerate(branches):
    by = 1.60 + i * 1.28
    card(s, 4.50, by, 4.35, 1.16, tint)
    tb(s, 4.76, by + 0.10, 3.9, 0.30, [P([(tag + "　" + t, 11, color, True)])])
    tb(s, 4.76, by + 0.44, 3.9, 0.62, [P([(d, 9.5, BODY, False)], line_spacing=1.15)])
conn(s, 8.85, 2.10, 9.28, 2.42)
conn(s, 8.85, 2.88, 9.28, 2.60)
card(s, 9.28, 1.60, 3.45, 1.55, "FFF0F0", "E8A5A5")
tb(s, 9.54, 1.74, 2.95, 0.32, [P([("② 全程无可用结果", 12, "B03A2E", True)])])
tb(s, 9.54, 2.12, 2.95, 0.95,
   [P([("如实告知 + 给出调整建议：宁可“没查到”，", 10, BODY, False),
       ("绝不编造", 10, "B03A2E", True), ("。", 10, BODY, False)], line_spacing=1.2)])
card(s, 9.28, 3.32, 3.45, 1.28, BLUE_BG, line=BLUE)
tb(s, 9.54, 3.44, 2.95, 0.32, [P([("③ 收束守卫（恒定）", 12, BLUE_D, True)])])
tb(s, 9.54, 3.80, 2.95, 0.75,
   [P([("最终作答指令恒带守卫：禁止编造数据 · 禁止引用检索结果中不存在的来源。", 9.5, BODY, False)], line_spacing=1.18)])
card(s, 0.6, 5.30, 12.13, 1.10, BLUE_BG2)
tb(s, 0.9, 5.46, 11.6, 0.78,
   [P([("机制价值：", 11, INK, True),
       ("从流程上抑制大模型幻觉 —— 每条结论可溯源、可证伪、可追责；配合 B 端维护与用户评价，形成“生成 → 评估 → 修正”的完整质量循环。", 10.5, BODY, False)], line_spacing=1.25)])

# ═══ S10 会话记忆与滚动压缩 ═══════════════════════════════════════════════
s = new_slide("窗口内保原文、窗口外滚动压缩为摘要并落库：上下文预算恒定，长会话不失忆。")
chrome(s, 10, "会话记忆与滚动压缩", "技术架构 · 记忆")
card(s, 0.6, 1.42, 3.85, 3.55, "FFF0F0", "E8A5A5")
tb(s, 0.88, 1.60, 3.3, 0.34, [P([("要解决的问题", 12.5, "B03A2E", True)])])
tb(s, 0.88, 2.02, 3.32, 2.80,
   [P([("长对话“失忆”：", 10.5, INK, True)], line_spacing=1.25),
    P([("上下文窗口有限，多轮之后早期信息被截断。", 10, BODY, False)], line_spacing=1.25, space_before=4),
    P([("实测案例：", 10.5, INK, True)], line_spacing=1.25, space_before=10),
    P([("连续查询 5 个省份采购均价后，追问“我之前不是查过安徽省的吗？”—— 模型已忘记安徽省的结果，只能道歉。", 10, BODY, False)], line_spacing=1.25, space_before=4)])
arrow_r(s, 4.52, 3.00, 0.36, 0.36)

sol = [
    ("窗口内 · 原文保留", "最近 4 轮对话逐字保留（HISTORY_WINDOW），细节零损耗", "2F6BD8"),
    ("窗口外 · 触发压缩", "更早轮次积压 ≥3 轮（COMPRESS_MIN_BATCH）即触发一次增量压缩", "C77E14"),
    ("LLM 摘要", "陈旧对话压缩为要点：实体清单 / 关键结论 / 纠正偏好", "7B61C4"),
    ("落库持久化", "摘要写入 session_memory（upto_qa_id 边界），重连 / 换端不丢失", "2E7D3A"),
]
for i, (t, d, color) in enumerate(sol):
    sy = 1.42 + i * 0.92
    card(s, 5.00, sy, 7.73, 0.78)
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 5.00, sy, 0.07, 0.78, color, radius=0.5)
    tb(s, 5.28, sy + 0.10, 2.35, 0.30, [P([(t, 11, color, True)])])
    tb(s, 5.28, sy + 0.42, 7.25, 0.32, [P([(d, 9.5, BODY, False)])])
card(s, 0.6, 5.42, 12.13, 1.28, BLUE_BG2)
tb(s, 0.9, 5.58, 11.6, 0.44, [P([("效果", 11.5, INK, True)])])
tb(s, 0.9, 5.94, 11.6, 0.66,
   [P([("上下文预算恒定：4 轮原文 + 1 段摘要，不随会话长度膨胀 · 压缩按轮次增量进行，token 成本可控 · 摘要边界（upto_qa_id）清晰，可重放、可校验、可恢复。", 10.5, BODY, False)], line_spacing=1.3)])

# ═══ S11 数据与存储设计 ═══════════════════════════════════════════════════
s = new_slide("MySQL 四张应用表 + PostgreSQL 结构化标的物 + 三库向量索引；一条清晰的数据链路。")
chrome(s, 11, "数据与存储设计", "技术架构 · 数据")
label(s, 0.6, 1.26, "MySQL · 应用四表")
tables = [
    ("user_account", "用户", "系统角色 admin / user · 业务角色 企业用户 / 自然人 · pbkdf2 口令散列", "2F6BD8"),
    ("qa_record", "问答记录", "问题 / 答案 / 来源 JSON / 维护状态 / 结果评价 —— B 端维护对象", "2E7D3A"),
    ("session_memory", "会话摘要", "滚动压缩摘要 summary + upto_qa_id 边界 —— 历史压缩落点", "7B61C4"),
    ("tracking_event", "埋点事件", "“发送”按钮 · 页面点击 · 次数（PRD 定义）+ 用户 / 会话标识", "C77E14"),
]
for i, (name, t, d, color) in enumerate(tables):
    tx = 0.6 + (i % 2) * 3.18
    ty = 1.62 + (i // 2) * 1.78
    card(s, tx, ty, 3.00, 1.64)
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, tx, ty, 0.07, 1.64, color, radius=0.5)
    tb(s, tx + 0.26, ty + 0.12, 2.6, 0.30, [P([(name, 11.5, color, True), ("　" + t, 9.5, MUTED, False)])])
    tb(s, tx + 0.26, ty + 0.48, 2.62, 1.05, [P([(d, 9.5, BODY, False)], line_spacing=1.2)])

card(s, 7.10, 1.62, 5.63, 1.35)
tb(s, 7.36, 1.76, 5.1, 0.32, [P([("PostgreSQL · bid_subjects", 11.5, INK, True), ("　结构化标的物", 9.5, MUTED, False)])])
tb(s, 7.36, 2.14, 5.15, 0.72,
   [P([("招标采购标的物训练数据 8790 行 × 17 字段（省份 / 采购人 / 预算 / 中标金额…），支撑地域、金额类结构化检索。", 9.5, BODY, False)], line_spacing=1.2)])
card(s, 7.10, 3.15, 5.63, 1.62)
tb(s, 7.36, 3.29, 5.1, 0.32, [P([("知识库向量索引（data/index）", 11.5, INK, True)])])
for nm, d, x in [("legal", "法条", 7.36), ("policy", "政策", 8.76), ("faq", "问答对（82 组）", 10.16)]:
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, 3.70, 1.28, 0.40, "E6F7F7", radius=0.3)
    tb(s, x, 3.78, 1.28, 0.28, [P([(nm + " · " + d, 9, "12777D", True)], align=PP_ALIGN.CENTER)])
tb(s, 7.36, 4.24, 5.15, 0.44,
   [P([("npz 向量矩阵 + meta.jsonl 元数据；行号是 Dense / Sparse / RRF 共用的去重键。", 9.5, BODY, False)], line_spacing=1.2)])

card(s, 0.6, 5.42, 12.13, 1.28, BLUE_BG2)
tb(s, 0.9, 5.58, 11.6, 0.34, [P([("数据链路", 11.5, INK, True)])])
flow = ["原始 xlsx（标的物 / 问答对）", "清洗导入 MySQL / PG", "embedding-3 向量化", "npz + meta.jsonl 索引", "混合检索层消费"]
fx = 0.9
for i, t in enumerate(flow):
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, fx, 5.98, 2.08, 0.52, WHITE, LINE)
    tb(s, fx + 0.06, 6.06, 1.96, 0.40, [P([(t, 9, BODY, True)], align=PP_ALIGN.CENTER, line_spacing=1.05)])
    if i < 4:
        tb(s, fx + 2.10, 6.04, 0.30, 0.4, [P([("→", 12, BLUE, True)], align=PP_ALIGN.CENTER)])
    fx += 2.42

# ═══ S12 工程化实践 ═══════════════════════════════════════════════════════
s = new_slide("不依赖重型向量库与框架：OpenAI 兼容客户端 + NumPy 自研检索，测试与文档制度化。")
chrome(s, 12, "工程化实践", "工程与实践")
eng = [
    ("多供应商 LLM 接入", "OpenAI 兼容 BaseClient + llm_factory 工厂；智谱 / DeepSeek 配置一键切换；模型目录驱动前端下拉可选", "7B61C4"),
    ("分层冒烟测试", "工具层（纯结构断言）→ Agent 层（事件流）→ 应用层（全链路）；“花钱调模型”的测试与免费断言严格分离", "2F6BD8"),
    ("统一工程链路", "uv 依赖管理 · pyproject 单一事实源 · .env 配置面（provider / model / embedding / rerank 均可调）", "C77E14"),
    ("文档制度", "开发文档 FR 需求矩阵 + 假设清单（A1–A12）评审回写 · 组件工作机制 Mermaid 图解 · 技术栈选型 ADR", "2E7D3A"),
    ("工作流资产化", "Skills 规划：new-agent-tool / rebuild-index / smoke / eval-retrieval —— 把踩坑经验沉淀为可复用流程", "199FA8"),
    ("安全基线", "JWT 鉴权 + 角色权限（路由守卫 + 后端双校验）· 回答经 DOMPurify 消毒、禁直插 v-html · 口令 pbkdf2 散列", "C05040"),
]
for i, (t, d, color) in enumerate(eng):
    ex = 0.6 + (i % 3) * 4.11
    ey = 1.32 + (i // 3) * 2.10
    card(s, ex, ey, 3.90, 1.96)
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, ex, ey, 0.07, 1.96, color, radius=0.5)
    tb(s, ex + 0.26, ey + 0.16, 3.5, 0.34, [P([(t, 12.5, INK, True)])])
    tb(s, ex + 0.26, ey + 0.58, 3.48, 1.28, [P([(d, 10, BODY, False)], line_spacing=1.25)])

# ═══ S13 Langfuse 可观测性 ═════════════════════════════════════════════════
s = new_slide("Langfuse 可观测性：问答结束后一次性上报 trace；追踪是增强不是依赖，任一环失败静默跳过。")
chrome(s, 13, "Langfuse 可观测性", "工程与实践 · 可观测")

# 左：设计原则
card(s, 0.6, 1.30, 4.35, 3.10, "F3F0FF", "D9D0F2")
tb(s, 0.88, 1.44, 3.85, 0.32, [P([("设计原则 · 追踪是增强，不是依赖", 12, "7B61C4", True)])])
principles = [
    ("01", "静默降级", "未启用、缺 Key、SDK 初始化失败或上报失败 → 一律跳过，绝不抛异常影响问答。"),
    ("02", "不阻塞流式", "问答结束后在 finally 中一次上报，SSE 逐 token 行为完全不变。"),
    ("03", "真实耗时", "span 持续时长≈0；真实回答耗时写入 metadata.total_seconds。"),
]
for i, (no, t, d) in enumerate(principles):
    py = 1.86 + i * 0.82
    tb(s, 0.88, py, 0.42, 0.28, [P([(no, 10.5, "7B61C4", True)])])
    tb(s, 1.34, py - 0.01, 3.30, 0.28, [P([(t, 10.5, INK, True)])])
    tb(s, 1.34, py + 0.27, 3.32, 0.50, [P([(d, 8.8, BODY, False)], line_spacing=1.12)])

# 左下：接入开关
card(s, 0.6, 4.58, 4.35, 2.02, BLUE_BG2)
tb(s, 0.88, 4.72, 3.85, 0.30, [P([("接入开关（.env）", 12, BLUE_D, True)])])
cfg = [
    ("LANGFUSE_ENABLED", "默认 false；置 true 且配双 Key 才启用"),
    ("LANGFUSE_PUBLIC_KEY / SECRET_KEY", "缺任一则跳过追踪"),
    ("LANGFUSE_HOST", "默认 https://cloud.langfuse.com"),
]
for i, (k, d) in enumerate(cfg):
    cy = 5.04 + i * 0.40
    tb(s, 0.88, cy, 3.85, 0.22, [P([(k, 8.8, BLUE_D, True)])])
    tb(s, 0.88, cy + 0.19, 3.85, 0.20, [P([(d, 8.4, BODY, False)])])
tb(s, 0.88, 6.22, 3.85, 0.22,
   [P([("SDK  ", 8.8, MUTED, False), ("langfuse>=5.1.0", 8.8, BODY, True)])])

# 右上：上报链路
label(s, 5.15, 1.28, "上报链路（问答结束后一次性写入）")
flow = [
    ("问答结束", "finally 收尾"),
    ("trace_qa()", "observability"),
    ("get_client()", "lru_cache 单例"),
    ("Langfuse", "Cloud / 自部署"),
]
for i, (t, d) in enumerate(flow):
    fx = 5.15 + i * 1.94
    last = i == len(flow) - 1
    card(s, fx, 1.66, 1.68, 0.78, "F3F0FF" if last else BLUE_BG,
         "7B61C4" if last else BLUE)
    tb(s, fx + 0.08, 1.75, 1.52, 0.26, [P([(t, 10, INK, True)], align=PP_ALIGN.CENTER)])
    tb(s, fx + 0.08, 2.05, 1.52, 0.26, [P([(d, 8, MUTED, False)], align=PP_ALIGN.CENTER)])
    if not last:
        arrow_r(s, fx + 1.74, 1.95, 0.15, 0.22, "9DB4E8")

# 右中：trace 结构
card(s, 5.15, 2.66, 7.65, 2.32)
tb(s, 5.40, 2.80, 7.10, 0.30, [P([("一条 trace 记录什么", 12, INK, True)])])
subs = [
    ("Input / Output", ["question 用户问题", "answer 最终回答", "sources 来源标题"], "E6F7F7", "12777D"),
    ("Metadata", ["model 回答模型", "tools 工具集合", "total_seconds · stages", "tool_count · source_count"], "FDF6EC", "9A6A0A"),
    ("Attributes", ["trace_name = qa", "as_type = agent", "user_id · session_id"], "F3F0FF", "7B61C4"),
]
for i, (t, lines, tint, color) in enumerate(subs):
    sx = 5.40 + i * 2.44
    card(s, sx, 3.18, 2.28, 1.62, tint)
    tb(s, sx + 0.14, 3.28, 2.0, 0.26, [P([(t, 10, color, True)])])
    for j, line in enumerate(lines):
        tb(s, sx + 0.14, 3.60 + j * 0.25, 2.02, 0.22,
           [P([("· " + line, 8.2, BODY, False)])])

# 右下：可观测价值
label(s, 5.15, 5.12, "可观测价值")
vals = [
    ("质量回溯", "回答与来源可逐条核对"),
    ("性能分析", "阶段耗时定位瓶颈"),
    ("工具行为", "工具选择与执行耗时"),
    ("会话关联", "按用户 / 会话筛选"),
]
for i, (t, d) in enumerate(vals):
    vx = 5.15 + i * 1.94
    card(s, vx, 5.48, 1.68, 1.08, BLUE_BG2)
    dot(s, vx + 0.16, 5.62, 0.10, BLUE)
    tb(s, vx + 0.34, 5.56, 1.24, 0.28, [P([(t, 9.8, INK, True)])])
    tb(s, vx + 0.16, 5.90, 1.40, 0.50, [P([(d, 8.2, BODY, False)], line_spacing=1.1)])

tb(s, 0.6, 6.70, 12.13, 0.30,
   [P([("价值：", 10, INK, True),
       ("把一次问答从“黑盒”变成可检索、可对比、可追溯的 trace —— 质量、时延与工具行为一目了然。", 10, BODY, False)])])

# ═══ S14 演进规划 ═════════════════════════════════════════════════════════
s = new_slide("先补评测与数据链路，再演进推荐与报表；开放 API 与多端为 PRD 二期范围。")
chrome(s, 14, "演进规划", "工程与实践 · 路线")
plan = [
    ("近期", "2F6BD8", [
        ("检索评测集 eval-retrieval", "黄金问题集 + hit@k，校准 RRF 融合参数（替代拍脑袋调参）"),
        ("数据导入链路 import-data", "xlsx → MySQL / PG → 重建索引，全链路一键化"),
        ("本地模型接入（Ollama）", "离线运行 · 零 API 成本，embedding 一并本地化"),
    ]),
    ("中期", "C77E14", [
        ("统计分析报表", "基于埋点与问答记录，输出使用量 / 满意度看板"),
        ("个性化推荐", "G3 二期深化：按用户行为推荐商机与知识"),
        ("知识图谱复杂推理", "实体关系图谱之上的多跳推理"),
    ]),
    ("远期", "6B7280", [
        ("标准数据 API 开放", "PRD 二期范围：问答与数据能力输出给企业系统"),
        ("多端覆盖", "移动 Web / 小程序（本期仅 PC Web）"),
        ("多知识库横向扩展", "新增领域只需导入语料 + 注册工具"),
    ]),
]
for c, (title, color, items) in enumerate(plan):
    px = 0.6 + c * 4.11
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, px, 1.30, 3.90, 0.50, color, radius=0.3)
    tb(s, px, 1.38, 3.90, 0.32, [P([(title, 12.5, WHITE, True)], align=PP_ALIGN.CENTER)])
    for i, (t, d) in enumerate(items):
        iy = 1.98 + i * 1.52
        card(s, px, iy, 3.90, 1.38)
        dot(s, px + 0.24, iy + 0.28, 0.12, color)
        tb(s, px + 0.48, iy + 0.18, 3.3, 0.32, [P([(t, 11, INK, True)])])
        tb(s, px + 0.48, iy + 0.56, 3.28, 0.72, [P([(d, 9.5, BODY, False)], line_spacing=1.2)])

# ═══ S15 总结 ═════════════════════════════════════════════════════════════
s = new_slide("三个关键词收束：闭环、自主、开放。")
chrome(s, 15, "总结", "小结")
summ = [
    ("产品闭环", "C 端问答 × B 端维护 × 用户评价：回答质量不是一次性的，而是可持续运营的资产", "2F6BD8"),
    ("技术自主", "自研混合检索（Dense + Sparse + RRF）· 滚动记忆压缩 · 质量关卡 —— 轻依赖，可离线演进", "199FA8"),
    ("开放可替换", "模型供应商（OpenAI 兼容）· 知识库（导入即用）· 工具（Pydantic 即插即用）三处皆可扩展", "7B61C4"),
]
for i, (t, d, color) in enumerate(summ):
    sx = 0.6 + i * 4.11
    card(s, sx, 1.50, 3.90, 2.30)
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, sx, 1.50, 3.90, 0.10, color, radius=0.5)
    tb(s, sx + 0.28, 1.82, 3.3, 0.40, [P([(t, 15, color, True)])])
    tb(s, sx + 0.28, 2.32, 3.36, 1.35, [P([(d, 10.5, BODY, False)], line_spacing=1.3)])
tb(s, 0, 4.35, 13.333, 0.6,
   [P([("“ 用数据洞察事实真相 ”", 22, BLUE, True)], align=PP_ALIGN.CENTER)])
tb(s, 0, 5.00, 13.333, 0.4,
   [P([("—— 每一个回答都有来源，每一次提问都被认真对待。", 11.5, MUTED, False)], align=PP_ALIGN.CENTER)])
if logo.exists():
    s.shapes.add_picture(str(logo), In(6.30), In(5.62), In(0.74), In(0.74))
tb(s, 0, 6.48, 13.333, 0.34,
   [P([("Kael Mind · 招投标问答机器人　|　谢谢观看", 11, INK, True)], align=PP_ALIGN.CENTER)])

prs.save(OUT)
print(f"✓ 已生成 {OUT}（{len(prs.slides._sldIdLst)} 页）")
