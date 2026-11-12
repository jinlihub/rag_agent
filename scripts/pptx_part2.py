# -*- coding: utf-8 -*-
"""part2: 第1-9页（封面/纲要/背景/用户/功能架构/业务流程/两个页面设计/交互）。"""
from pptx_part1 import *  # noqa
from pptx_part1 import _paras


def s01_cover(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bar(slide, 0, 0, SW, SH, NAVY)
    # 装饰：右侧圆环与数据方块
    ring = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(9.4), Inches(-1.5),
                                  Inches(6.2), Inches(6.2))
    ring.fill.background()
    ring.line.color.rgb = BLUE
    ring.line.width = Pt(2.5)
    ring.shadow.inherit = False
    for i, c in enumerate([SKY, BLUE, SKY, BLUE, SKY, BLUE]):
        box(slide, 9.7 + i * 0.44, 5.95, 0.3, 0.3, [], fill=c)
    box(slide, 11.9, 1.3, 0.32, 0.32, [], fill=SKY, radius=0.5)
    box(slide, 10.7, 4.7, 0.5, 0.5, [], fill=BLUE, radius=0.5)
    chip(slide, 0.95, 2.0, 3.15, 0.52, '产品设计与技术架构汇报', fill=BLUE, size=13)
    text(slide, 0.90, 2.62, 11.6, 1.15,
         [{'t': '招投标智能问答机器人', 's': 40, 'b': True, 'c': WHITE}])
    text(slide, 0.95, 3.90, 11.0, 0.5,
         [{'t': '用数据洞察事实真相 —— 让招投标信息「问得到 · 答得准 · 可维护」',
           's': 16, 'c': SKY}])
    text(slide, 0.95, 6.55, 8.0, 0.35,
         [{'t': '2026-10 ｜ 前端架构组 ｜ 评审稿 V1.0', 's': 11, 'c': SKY}])
    text(slide, 0.95, 7.08, 8.5, 0.3,
         [{'t': '图示建议：品牌视觉背景 / 抽象数据流线条', 's': 9, 'c': MUTE}])
    text(slide, 12.30, 7.04, 0.55, 0.32,
         [{'t': '01', 's': 11, 'b': True, 'c': SKY, 'a': R}])
    note(slide, '各位好。今天汇报招投标智能问答机器人的产品设计与技术架构。项目定位一句话：'
                '把分散在政策、招标、舆情、企业、价格、商品六大信息域的招投标数据，'
                '变成企业全员可对话的数据资产。汇报分产品设计与技术架构两条主线，'
                '最后给出里程碑与风险，预计15分钟。')
    return slide


def s02_agenda(prs):
    slide = deck(prs, '汇报纲要', '今天讲什么：四个篇章', 2, '四板块步骤条 / 章节导航')
    groups = [
        ('产品篇', NAVY, ['背景与目标', '用户与场景', '产品功能架构', '核心业务流程', '页面与交互设计']),
        ('技术篇', BLUE, ['技术架构总览', '技术栈概览', '核心算法思想', '数据资产与模型']),
        ('工程篇', ORANGE, ['工程化与质量保障', '性能 · 安全 · 可访问性']),
        ('计划篇', GREEN, ['里程碑与风险', '总结与展望']),
    ]
    x = 0.62
    for name, color, items in groups:
        box(slide, x, 1.95, 2.92, 0.62, [{'t': name, 's': 15, 'b': True, 'c': WHITE}], fill=color)
        paras = [{'t': it, 's': 11.5, 'c': DARK, 'sa': 7, 'a': L} for it in items]
        box(slide, x, 2.57, 2.92, 3.6, paras, fill=PALE, line=SKY, align=L,
            anchor=MSO_ANCHOR.TOP)
        x += 3.06
    text(slide, 0.62, 6.45, 12.09, 0.4,
         [{'t': '材料基线：《产品需求文档》《开发说明文档》 + 设计稿截图 + 样例数据（8,790 条标的物 / 82 条问答对）',
           's': 11, 'c': GRAY, 'a': C}])
    note(slide, '汇报分四个篇章：产品篇讲清楚"做什么、给谁用、长什么样"；'
                '技术篇讲清楚"架构怎么搭、技术怎么选、算法什么思想"；'
                '工程篇讲质量与非功能保障；计划篇给出里程碑、风险与展望。'
                '全部内容以产品需求文档和开发说明为基线，缺口处已标注假设。')
    return slide


def s03_background(prs):
    slide = deck(prs, '产品篇 · 01', '项目背景与目标', 3, '左痛点右目标对照图')
    pains = [
        ('信息不对称', '公告、政策、企业、价格等信息分散在各地交易平台与第三方平台'),
        ('检索效率低', '信息量庞大，人工搜索与筛选耗时耗力'),
        ('专业门槛高', '法规与流程复杂，需要专业解读与建议'),
    ]
    x = 0.62
    for t, d in pains:
        box(slide, x, 1.70, 3.92, 1.32,
            [{'t': t, 's': 14, 'b': True, 'c': NAVY, 'sa': 4},
             {'t': d, 's': 10.5, 'c': GRAY}], fill=PALE, line=SKY)
        x += 4.08
    box(slide, 2.67, 3.30, 8.0, 0.66,
        [{'t': '“ 用数据洞察事实真相 ”', 's': 17, 'b': True, 'c': WHITE}], fill=NAVY)
    goals = [
        ('智能检索', '关键词/自然语言快速获取公告、中标、项目信息，可筛选排序'),
        ('智能回答', '招投标专业问题即问即答，回答结构化、来源可溯'),
        ('个性化服务', '按需求与行为推荐信息（后续演进方向）'),
    ]
    x = 0.62
    for t, d in goals:
        box(slide, x, 4.22, 3.92, 1.30,
            [{'t': t, 's': 14, 'b': True, 'c': BLUE, 'sa': 4},
             {'t': d, 's': 10.5, 'c': GRAY}], fill=LIGHT)
        x += 4.08
    box(slide, 0.62, 5.80, 12.09, 0.75,
        [{'runs': [('本期范围：', 12, True, NAVY),
                   ('PC Web 问答机器人（C 端问答 + B 端维护后台）', 12, False, DARK),
                   ('　｜　范围外：', 12, True, NAVY),
                   ('标准 API 接口 · 移动端/客户端 · 个性化推荐', 12, False, DARK)]}],
        fill=PALE, line=SKY)
    note(slide, '招投标是信息密集型行业，三个痛点：信息不对称、检索效率低、专业门槛高。'
                '产品的主张是"用数据洞察事实真相"。对应三个目标——智能检索、智能回答、'
                '个性化服务。本期聚焦 PC Web 问答机器人，先解决"问得到、答得准"；'
                'API 开放、移动端和推荐放到后续迭代，范围边界清晰。')
    return slide


def s04_users(prs):
    slide = deck(prs, '产品篇 · 02', '用户与场景', 4, '用户画像卡片（4 类业务角色）')
    box(slide, 0.62, 1.64, 6.00, 0.52,
        [{'t': 'C 端提问用户：企业用户（如 XX公司） · 自然人（如 张工）',
          's': 12, 'b': True, 'c': NAVY}], fill=LIGHT, line=SKY)
    box(slide, 6.78, 1.64, 5.93, 0.52,
        [{'t': 'B 端管理员：问答质量维护（标记 / 编辑 / 免维护）',
          's': 12, 'b': True, 'c': NAVY}], fill=LORANGE, line=ORANGE)
    personas = [
        ('企业老板', '市场行情：某产品采购价与成交动态', '“挖掘机近期市场行情如何？”'),
        ('采购人员', '优质厂家 · 类似项目招标文件范本', '“EPC 项目招标范本有哪些？”'),
        ('技术研发', '产品技术参数查询', '“60 型挖掘机铲斗容量是多少？”'),
        ('销售人员', '开拓商机 · 寻找招标线索', '“近半年合肥哪些企业中标？”'),
    ]
    x = 0.62
    for t, need, q in personas:
        box(slide, x, 2.38, 2.92, 0.55, [{'t': t, 's': 13.5, 'b': True, 'c': WHITE}], fill=BLUE)
        box(slide, x, 2.93, 2.92, 2.15,
            [{'t': need, 's': 11, 'c': DARK, 'sa': 8},
             {'t': q, 's': 10.5, 'b': True, 'c': GRAY, 'sa': 0}],
            fill=PALE, line=SKY, anchor=MSO_ANCHOR.TOP)
        x += 3.06
    box(slide, 0.62, 5.35, 12.09, 1.05,
        [{'t': '设计稿原例（真实问句）', 's': 10.5, 'b': True, 'c': SKY, 'sa': 4},
         {'t': '「最新的关于EPC项目的计划信息？近半年安徽合肥区域有哪些企业中标？」',
          's': 15, 'b': True, 'c': WHITE}], fill=NAVY)
    note(slide, '用户分两端：C 端提问用户按企业角色有四类典型画像——老板看行情、'
                '采购找厂家和范本、研发查参数、销售找商机；系统层面区分企业用户与自然人。'
                'B 端管理员负责回答质量维护。下方是设计稿里的真实问句：'
                '一句话同时问到"项目计划"和"区域中标统计"，这正是结构化回答要解决的核心场景。')
    return slide


def s05_features(prs):
    slide = deck(prs, '产品篇 · 03', '产品功能架构', 5, '分层功能架构图（本页已绘制，可按视觉规范重绘）')
    layers = [
        ('应用层', NAVY, LIGHT),
        ('支撑层', BLUE, LIGHT),
        ('能力层', ORANGE, LORANGE),
        ('数据层', GRAY, LGRAY),
    ]
    y = 1.72
    for name, lc, cc in layers:
        box(slide, 0.62, y, 1.55, 1.02, [{'t': name, 's': 14, 'b': True, 'c': WHITE}], fill=lc)
        y += 1.16
    # 应用层
    box(slide, 2.50, 1.92, 4.95, 0.62,
        [{'t': 'C 端 · 问答机器人（对话提问 · 结构化回答）', 's': 12, 'b': True, 'c': NAVY}], fill=LIGHT)
    box(slide, 7.65, 1.92, 5.05, 0.62,
        [{'t': 'B 端 · 维护后台（列表 · 筛选 · 维护操作）', 's': 12, 'b': True, 'c': NAVY}], fill=LIGHT)
    # 支撑层
    box(slide, 2.50, 3.08, 4.95, 0.62,
        [{'t': '用户管理（注册 · 登录 · 角色）', 's': 12, 'c': DARK}], fill=LIGHT)
    box(slide, 7.65, 3.08, 5.05, 0.62,
        [{'t': '统计分析（数据埋点：发送按钮点击）', 's': 12, 'c': DARK}], fill=LIGHT)
    # 能力层
    caps = ['智能检索', '智能回答', '个性化推荐（后续）']
    x = 2.50
    for cpt in caps:
        box(slide, x, 4.24, 3.30, 0.62, [{'t': cpt, 's': 12, 'b': True, 'c': DARK}], fill=LORANGE)
        x += 3.45
    # 数据层
    domains = ['政策', '招标', '舆情', '企业', '价格', '商品']
    x = 2.42
    for d in domains:
        box(slide, x, 5.40, 1.62, 0.62, [{'t': d, 's': 12.5, 'b': True, 'c': DARK}], fill=LGRAY)
        x += 1.73
    box(slide, 0.62, 6.40, 12.09, 0.50,
        [{'t': '数据来源：各地公共资源交易平台/交易中心 · 新闻网站与舆情接口 · 爱企查/企查查 · 爱采购/1688',
          's': 11, 'c': GRAY}], fill=PALE, line=SKY)
    note(slide, '产品功能分四层：数据层是六大信息域的采集解析底座；能力层是算法能力——'
                '检索与生成，细节由算法文档承载；支撑层是用户管理与埋点统计；'
                '应用层对用户可见的是 C 端问答机器人和 B 端维护后台。'
                '本期边界：不做标准 API、不做移动端，推荐能力预留。')
    return slide


def s06_flow(prs):
    slide = deck(prs, '产品篇 · 04', '核心业务流程', 6, '端到端流程图 + 反馈回路（本页已绘制）')
    text(slide, 0.80, 1.60, 5.2, 0.3,
         [{'t': '数据侧 · 离线资产化', 's': 10.5, 'b': True, 'c': BLUE, 'a': C}])
    text(slide, 6.10, 1.60, 5.0, 0.3,
         [{'t': '应用侧 · 在线问答', 's': 10.5, 'b': True, 'c': NAVY, 'a': C}])
    text(slide, 11.15, 1.60, 1.5, 0.3,
         [{'t': '运营侧', 's': 10.5, 'b': True, 'c': ORANGE, 'a': C}])
    steps = [
        ('信息采集', '六大信息域\n多源采集', BLUE),
        ('解析清洗', '字段抽取\n清洗去噪', BLUE),
        ('结构化入库', 'MySQL\n向量库', BLUE),
        ('知识检索', 'RAG\n语义检索', NAVY),
        ('智能生成', 'LLM+Agent\n生成回答', NAVY),
        ('结构化展示', '分点列表\n来源可溯', NAVY),
        ('人工维护', '标记·编辑\n免维护', ORANGE),
    ]
    x = 0.80
    for i, (name, cap, color) in enumerate(steps):
        shp = slide.shapes.add_shape(MSO_SHAPE.CHEVRON, Inches(x), Inches(2.0),
                                     Inches(1.78), Inches(0.95))
        shp.fill.solid()
        shp.fill.fore_color.rgb = color
        shp.line.fill.background()
        shp.shadow.inherit = False
        tf = shp.text_frame
        tf.word_wrap = True
        _paras(tf, [{'t': name, 's': 12, 'b': True, 'c': WHITE}])
        cx = x + 0.89
        lines = cap.split('\n')
        text(slide, cx - 0.85, 3.08, 1.70, 0.75,
             [{'t': ln, 's': 9, 'c': MUTE, 'sa': 1, 'a': C} for ln in lines])
        x += 1.66
    arrow(slide, 1.05, 4.20, 1.25, 0.55, fill=ORANGE, direction='l')
    box(slide, 2.50, 4.18, 9.60, 0.62,
        [{'t': '反馈闭环：维护结果沉淀为标准答案 → 反哺知识库与回答质量（系统越用越准）',
          's': 12.5, 'b': True, 'c': DARK}], fill=LORANGE, line=ORANGE)
    box(slide, 0.62, 5.30, 12.09, 1.10,
        [{'t': '一句话', 's': 10.5, 'b': True, 'c': MUTE, 'sa': 5},
         {'t': '离线把数据变资产 ｜ 在线把问题变答案 ｜ 运营把答案变准', 's': 17, 'b': True, 'c': NAVY}],
        fill=PALE, line=SKY)
    note(slide, '核心业务流程七步：从多源采集、解析清洗、结构化入库，到知识检索、'
                '智能生成、结构化展示，最后落到人工维护。关键设计是最后一环——'
                '机器回答不是终点，管理员在后台的标记与编辑会沉淀为标准答案，'
                '反哺知识库，让系统越用越准。这是产品区别于纯搜索引擎的质量闭环。')
    return slide


def s07_page_chat(prs):
    slide = deck(prs, '产品篇 · 05', '页面设计 · 用户问答页（C 端）', 7,
                 '界面线框（可替换为设计稿截图）')
    # 线框
    box(slide, 0.62, 1.66, 5.35, 5.10, [], fill=WHITE, line=SKY, lw=1.5)
    bar(slide, 0.62, 1.66, 5.35, 0.50, LIGHT)
    text(slide, 0.85, 1.78, 4.9, 0.3,
         [{'t': '信息官 · 智能问答（机器人名称待确认）', 's': 11, 'b': True, 'c': NAVY}])
    box(slide, 0.85, 2.38, 3.55, 1.72,
        [{'t': '根据目前的招标信息，EPC 计划阶段的项目共 5 个：', 's': 8.5, 'c': DARK, 'sa': 2, 'a': L},
         {'t': '1、XXX EPC项目，发布地址：XXX', 's': 8.5, 'c': DARK, 'sa': 2, 'a': L},
         {'t': '2、XXX EPC项目，发布地址：XXX', 's': 8.5, 'c': DARK, 'sa': 2, 'a': L},
         {'t': '……', 's': 8.5, 'c': DARK, 'sa': 2, 'a': L},
         {'t': '合肥近半年中标：1、XXX公司，188万元', 's': 8.5, 'b': True, 'c': NAVY, 'a': L}],
        fill=PALE, line=SKY, radius=0.15, anchor=MSO_ANCHOR.TOP)
    box(slide, 3.05, 4.28, 2.70, 0.62,
        [{'t': '最新的EPC项目计划？近半年合肥中标企业？', 's': 8.5, 'c': WHITE}],
        fill=BLUE, radius=0.25)
    for i in range(3):
        d = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.92 + i * 0.20),
                                   Inches(5.18), Inches(0.11), Inches(0.11))
        d.fill.solid()
        d.fill.fore_color.rgb = SKY
        d.line.fill.background()
        d.shadow.inherit = False
    text(slide, 1.58, 5.10, 2.0, 0.3, [{'t': '生成中…', 's': 9, 'c': MUTE}])
    box(slide, 0.85, 5.95, 3.60, 0.50,
        [{'t': '请输入问题，Shift+Enter 换行', 's': 9, 'c': MUTE, 'a': L}],
        fill=WHITE, line=SKY)
    box(slide, 4.60, 5.90, 1.05, 0.58, [{'t': '发 送', 's': 11, 'b': True, 'c': WHITE}], fill=NAVY)
    # 要点
    bullets(slide, 6.35, 1.80, 6.35, 5.0, [
        ('对话式布局 —— ', '消息流 + 底部固定输入区，聚焦问答本身'),
        ('结构化回答 —— ', '分点列表：项目带发布地址、中标带金额，来源可核验'),
        ('生成中反馈 —— ', '提问后立即出现生成状态，回答流式渐现（假设，待联调确认）'),
        ('输入细节 —— ', 'Enter 发送 · Shift+Enter 换行 · 发送中按钮禁用防重复'),
        ('收藏指令 —— ', '输入指定指令查看收藏说明（指令形式待产品确认）'),
        ('数据埋点 —— ', '点击「发送」即上报：事件「发送」按钮 · 属性「页面点击」· 值「次数」'),
    ], size=12, sa=13)
    note(slide, 'C 端是纯对话式界面：用户提问与机器人回答分侧展示，回答以分点结构化呈现——'
                '项目名带发布地址、中标单位带金额，来源可核验。'
                '底部输入区细节到位：Enter 发送、Shift+Enter 换行，发送按钮同时是埋点按钮。'
                '左侧线框还原自设计稿，机器人名称 OCR 识别为"信息官"，待确认。')
    return slide


def s08_page_admin(prs):
    slide = deck(prs, '产品篇 · 06', '页面设计 · 维护后台（B 端）', 8,
                 '界面线框（可替换为设计稿截图）')
    # 线框
    box(slide, 0.62, 1.66, 7.45, 5.10, [], fill=WHITE, line=SKY, lw=1.5)
    bar(slide, 0.62, 1.66, 7.45, 0.46, NAVY)
    text(slide, 0.85, 1.76, 5.0, 0.3,
         [{'t': '招投标问答机器人管理后台', 's': 11, 'b': True, 'c': WHITE}])
    text(slide, 6.30, 1.76, 1.6, 0.3, [{'t': '管理员 ▾', 's': 10, 'c': WHITE, 'a': R}])
    text(slide, 0.85, 2.18, 4.0, 0.28,
         [{'t': '首页 > 用户问答列表', 's': 9.5, 'c': MUTE}])
    filters = [('用户名称', '请输入用户名称'), ('问题关键词', '请输入关键词'), ('用户角色', '请选择'),
               ('维护结果', '未维护 ▾'), ('结果评价', '无 ▾'), ('问题时间', 'Start — End')]
    for i, (lb, val) in enumerate(filters):
        fx = 0.85 + (i % 3) * 2.32
        fy = 2.52 + (i // 3) * 0.78
        box(slide, fx, fy, 2.20, 0.66,
            [{'t': lb, 's': 8, 'c': MUTE, 'sa': 1, 'a': L},
             {'t': val, 's': 9, 'c': DARK, 'a': L}],
            fill=WHITE, line=SKY, anchor=MSO_ANCHOR.TOP)
    box(slide, 6.32, 3.30, 0.90, 0.50, [{'t': '查 询', 's': 10.5, 'b': True, 'c': WHITE}], fill=BLUE)
    # 表格
    cols = [0.40, 1.12, 1.62, 0.62, 0.62, 0.70, 0.70, 1.27]
    heads = ['序号', '用户问题', '智能回答', '用户', '角色', '创建时间', '修改时间', '操作']
    rows = [
        ['1', '最新的EPC项目计划？近半年合肥…', '根据目前的招标信息，EPC计划阶段项目共5个…',
         '张工', '自然人', '11-15 08:08', '11-15 09:08', '标记正确 ｜ 编辑 ｜ 免维护'],
        ['2', '单一来源公示被“质疑”怎么办？', '供应商只能在公示期间提出异议，采购人收到…',
         'XX公司', '企业用户', '11-15 08:08', '11-15 09:08', '标记正确 ｜ 编辑 ｜ 免维护'],
    ]
    tbl_shape = slide.shapes.add_table(3, 8, Inches(0.85), Inches(4.42),
                                       Inches(sum(cols)), Inches(1.30))
    tbl = tbl_shape.table
    tbl.first_row = True
    for j, w in enumerate(cols):
        tbl.columns[j].width = Inches(w)
    tbl.rows[0].height = Inches(0.34)
    tbl.rows[1].height = Inches(0.48)
    tbl.rows[2].height = Inches(0.48)
    for j, h in enumerate(heads):
        set_cell(tbl.cell(0, j), h, size=8, bold=True, color=WHITE, fill=NAVY)
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            set_cell(tbl.cell(i + 1, j), v, size=7.5,
                     fill=PALE if i % 2 == 0 else WHITE,
                     align=L if j in (1, 2) else C)
    text(slide, 0.85, 6.28, 6.95, 0.3,
         [{'t': '共 432 条　‹ 1 2 3 … 44 ›　前往 [ ] 页', 's': 9, 'c': GRAY, 'a': R}])
    # 要点
    bullets(slide, 8.40, 1.90, 4.30, 5.0, [
        ('六条件筛选 —— ', '用户名称 / 关键词 / 角色 / 维护结果（默认未维护）/ 结果评价 / 时间范围'),
        ('八列全景 —— ', '序号·问题·回答·用户·角色·创建/修改时间·操作'),
        ('三类操作 —— ', '标记正确 · 编辑修正 · 不需要维护'),
        ('操作留痕 —— ', '维护后「修改时间」自动刷新'),
        ('分页 —— ', '总数 + 页码 + 跳页（示例 432 条）'),
    ], size=11, sa=12)
    note(slide, 'B 端维护后台围绕"用户问答列表"展开：六个筛选条件默认锁定"未维护"，'
                '让管理员优先处理待维护数据；八列信息完整呈现一次问答的全貌；'
                '三类操作——标记正确、编辑修正、不需要维护——构成质量闭环，'
                '且所有操作以修改时间留痕。线框还原自设计稿。')
    return slide


def s09_interaction(prs):
    slide = deck(prs, '产品篇 · 07', '交互说明：时序与状态', 9, '提问时序图 + 维护状态机')
    chip(slide, 0.62, 1.64, 6.05, 0.44, 'C 端 · 提问—回答时序', fill=NAVY, size=12.5)
    steps = [
        '① 输入问题（Shift+Enter 换行）',
        '② 点击发送 → 埋点+1 · 按钮禁用 · 消息立即上屏',
        '③ 生成中 · 流式渐现（Typing 指示）',
        '④ 渲染完成 · 自动滚动定位最新回答',
    ]
    y = 2.30
    for i, st in enumerate(steps):
        box(slide, 1.55, y, 4.60, 0.54, [{'t': st, 's': 10.5, 'c': DARK, 'a': L}],
            fill=LIGHT, align=L)
        if i < 3:
            arrow(slide, 3.70, y + 0.58, 0.30, 0.24, fill=BLUE, direction='d')
        y += 0.86
    box(slide, 1.55, 5.86, 4.60, 0.62,
        [{'t': '异常分支：失败/超时 → 错误态 + 重试，用户输入保留', 's': 10, 'b': True, 'c': RED}],
        fill=LRED, line=RED)
    chip(slide, 6.97, 1.64, 5.74, 0.44, 'B 端 · 维护状态机', fill=NAVY, size=12.5)
    box(slide, 7.30, 3.30, 1.70, 0.75, [{'t': '未维护', 's': 13, 'b': True, 'c': NAVY}],
        fill=WHITE, line=BLUE, lw=1.5)
    box(slide, 10.55, 2.42, 1.95, 0.70, [{'t': '已维护', 's': 13, 'b': True, 'c': DARK}],
        fill=LIGHT, line=BLUE)
    box(slide, 10.55, 4.10, 1.95, 0.70, [{'t': '不需要维护', 's': 12, 'b': True, 'c': DARK}],
        fill=LGRAY, line=GRAY)
    arrow(slide, 9.10, 2.58, 1.30, 0.38, fill=BLUE)
    arrow(slide, 9.10, 4.26, 1.30, 0.38, fill=ORANGE)
    text(slide, 8.95, 2.20, 1.65, 0.3, [{'t': '标记正确 / 编辑保存', 's': 9, 'c': BLUE, 'a': C}])
    text(slide, 8.95, 3.94, 1.65, 0.3, [{'t': '不需要维护', 's': 9, 'c': ORANGE, 'a': C}])
    text(slide, 7.30, 5.15, 5.20, 0.3,
         [{'t': '操作成功 → 修改时间刷新 · 列表状态即时更新', 's': 9.5, 'c': MUTE, 'a': L}])
    box(slide, 0.62, 6.35, 12.09, 0.60,
        [{'t': '全局规范：加载 / 空 / 错误 / 超时四态统一文案　·　纯键盘完成全流程　·　不可逆操作二次确认',
          's': 12.5, 'b': True, 'c': WHITE}], fill=NAVY)
    note(slide, '交互上抓两条主线：C 端是提问时序——点击发送立即上屏、埋点上报、'
                '生成中流式渐现，失败可重试且输入不丢；B 端是维护状态机——'
                '未维护经三类操作流转到已维护或不需要维护，修改时间留痕。'
                '全局统一加载、空、错误、超时四态文案，并保证纯键盘可完成全流程，'
                '这是可访问性的硬要求。')
    return slide
