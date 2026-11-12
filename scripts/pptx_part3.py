# -*- coding: utf-8 -*-
"""part3: 第10-17页（技术架构/技术栈/算法/数据/工程/性能安全/里程碑/总结）+ 主函数。"""
from pptx_part2 import *  # noqa


def s10_arch(prs):
    slide = deck(prs, '技术篇 · 01', '技术架构总览', 10, '分层架构图（本页已绘制）')
    layers = [
        ('用户层', 'PC Web', NAVY, LIGHT),
        ('前端应用层', 'Vue 3 + TS', NAVY, LIGHT),
        ('接入层', 'Nginx', BLUE, LIGHT),
        ('后端服务层', 'Spring Boot', BLUE, LIGHT),
        ('算法服务层', 'LLM + Agent', ORANGE, LORANGE),
        ('数据层', 'MySQL 等', GRAY, LGRAY),
    ]
    y = 1.68
    for name, sub, lc, _ in layers:
        box(slide, 0.62, y, 1.75, 0.75,
            [{'t': name, 's': 12.5, 'b': True, 'c': WHITE, 'sa': 0},
             {'t': sub, 's': 8, 'c': WHITE, 'sa': 0}], fill=lc)
        y += 0.86
    box(slide, 2.55, 1.78, 10.10, 0.55,
        [{'t': 'PC Web 浏览器（Chrome / Edge 等现代浏览器）', 's': 11.5, 'c': DARK}], fill=LIGHT)
    for i, t in enumerate(['C 端 · 问答 SPA', 'B 端 · 管理后台 SPA']):
        box(slide, 2.55 + i * 2.78, 2.64, 2.62, 0.55,
            [{'t': t, 's': 11.5, 'b': True, 'c': NAVY}], fill=LIGHT)
    box(slide, 8.10, 2.64, 4.55, 0.55,
        [{'t': '公共层：请求封装 · 埋点 SDK · 权限路由', 's': 11.5, 'c': DARK}], fill=LIGHT)
    box(slide, 2.55, 3.50, 10.10, 0.55,
        [{'t': '静态资源 · 反向代理 · SSE 透传 · HTTPS（C/B 端同域单入口）', 's': 11.5, 'c': DARK}],
        fill=LIGHT)
    for i, t in enumerate(['用户管理', '问答服务', '维护管理', '统计分析']):
        box(slide, 2.55 + i * 2.55, 4.36, 2.42, 0.55,
            [{'t': t, 's': 11.5, 'b': True, 'c': DARK}], fill=LIGHT)
    text(slide, 2.55, 4.94, 10.1, 0.25,
         [{'t': 'MyBatis-Plus 持久层 · Spring Security + JWT 鉴权 · Redis 会话缓存',
           's': 9, 'c': MUTE, 'a': L}])
    alg = ['LLM+Agent（LLAMA/GLM 微调 · 星火API）', '向量检索 · RAG', '传统NLP（分词 · NER · 倒排）']
    for i, t in enumerate(alg):
        box(slide, 2.55 + i * 3.42, 5.24, 3.28, 0.55,
            [{'t': t, 's': 10.5, 'b': True, 'c': DARK}], fill=LORANGE)
    for i, t in enumerate(['MySQL(RDS)', 'MongoDB', 'Redis', '向量库 Faiss', 'OSS 文件']):
        box(slide, 2.55 + i * 2.05, 6.10, 1.94, 0.55,
            [{'t': t, 's': 10.5, 'c': DARK}], fill=LGRAY)
    note(slide, '技术架构前后端分离，共六层：用户层 PC Web；前端应用层是 Vue 3 单页应用，'
                'C 端 B 端同仓隔离、公共层复用请求、埋点与权限；接入层 Nginx '
                '承担静态资源、反向代理与 SSE 透传，两端同域单入口部署；'
                '后端 Spring Boot 加 MyBatis-Plus 提供四类业务服务，'
                'Spring Security 加 JWT 鉴权，Redis 缓存会话；'
                '算法服务承载 LLM+Agent 与向量检索；数据层 MySQL 为主库、'
                'MongoDB 存非结构化数据、Faiss 向量库支撑语义检索、OSS 存文件。')
    return slide


def s11_stack(prs):
    slide = deck(prs, '技术篇 · 02', '技术栈概览', 11, '技术栈矩阵表')
    data = [
        ('前端框架', 'Vue 3 + TypeScript', 'Composition API；C/B 两端同仓隔离'),
        ('构建 / 组件库', 'Vite + Element Plus', '按需引入；主题 CSS Variables 定制'),
        ('路由 / 状态', 'Vue Router 4 + Pinia', 'History 模式；auth / chat / adminQa 分 store'),
        ('请求层', 'Axios 封装 + SSE', '统一鉴权与错误码；回答走流式通道'),
        ('表单校验', 'Element Plus Form + async-validator', '筛选不强制校验；时间范围逻辑校验'),
        ('测试', 'Vitest + Playwright', '验收标准 AC 脚本化，冒烟进 CI'),
        ('代码质量', 'ESLint + Prettier + TS strict', 'pre-commit 与 CI 双重门禁'),
        ('后端', 'Spring Boot + MyBatis-Plus', 'Spring Security + JWT；Redis 缓存'),
        ('数据存储', 'MySQL(RDS) · MongoDB · Redis · Faiss', '结构化 / 非结构化 / 缓存 / 向量分层'),
        ('工程链', 'GitLab + Jenkins + 禅道', '沿用开发说明指定基础设施'),
        ('兼容 / 无障碍', 'Chrome/Edge ≥ 90 · WCAG 2.1 AA', '不支持 IE；键盘全流程'),
    ]
    tbl_shape = slide.shapes.add_table(12, 3, Inches(0.62), Inches(1.66),
                                       Inches(12.09), Inches(4.95))
    tbl = tbl_shape.table
    tbl.first_row = True
    tbl.columns[0].width = Inches(2.30)
    tbl.columns[1].width = Inches(4.60)
    tbl.columns[2].width = Inches(5.19)
    for i in range(12):
        tbl.rows[i].height = Inches(0.41)
    for j, h in enumerate(['领域', '选型', '要点']):
        set_cell(tbl.cell(0, j), h, size=11.5, bold=True, color=WHITE, fill=NAVY)
    for i, row in enumerate(data):
        for j, v in enumerate(row):
            set_cell(tbl.cell(i + 1, j), v, size=10.5, bold=(j == 0),
                     color=NAVY if j == 0 else DARK,
                     fill=PALE if i % 2 == 0 else WHITE,
                     align=L if j > 0 else C)
    text(slide, 0.62, 6.68, 12.09, 0.3,
         [{'t': '每项选型均含「选型理由 · 适用场景 · 替代方案 · 注意事项」，详见《技术栈.md》。',
           's': 10, 'c': MUTE, 'a': C}])
    note(slide, '技术栈与开发说明保持一致：Vue 加 Element 体系、Spring Boot、MySQL、'
                'Redis、Jenkins，在此基础上按当前工程实践具体化——Vue 3 加 TypeScript、'
                'Vite 构建、Pinia 状态管理、Axios 加 SSE 流式通道。'
                '关键升级点都已标注假设；每一项的选型理由、替代方案与注意事项'
                '在《技术栈.md》中逐项可评审。')
    return slide


def s12_algo(prs):
    slide = deck(prs, '技术篇 · 03', '核心算法思想（LLM + Agent）', 12, '算法分层示意')
    items = [
        ('中枢大模型层', 'LLAMA / GLM · MSAgent-Bench 微调 · 星火 API'),
        ('数据收集与管理层', '采集 · 预处理 · 存储（MySQL / MongoDB / 向量库）'),
        ('工具库与检索层', '工具注册 · 版本管理 · 多维检索与推荐'),
        ('记忆控制层', '知识检索（招标/供应商/物资）· Prompt 管理'),
        ('API 集成与管理层', '统一接口规范 · 认证机制'),
        ('实际应用层', '应用部署 · 性能监控与优化'),
    ]
    y = 1.72
    for t, d in items:
        box(slide, 0.62, y, 5.55, 0.68,
            [{'t': t, 's': 12, 'b': True, 'c': NAVY, 'sa': 1, 'a': L},
             {'t': d, 's': 9, 'c': GRAY, 'a': L}],
            fill=LIGHT, align=L, anchor=MSO_ANCHOR.MIDDLE)
        y += 0.80
    chip(slide, 6.55, 1.72, 2.4, 0.42, '关键思想', fill=BLUE, size=12)
    bullets(slide, 6.55, 2.30, 6.15, 4.6, [
        ('RAG 思想 —— ', '先检索招投标知识，再生成带来源的回答，机制上压低幻觉'),
        ('传统 NLP 辅助 —— ', '分词 · 命名实体识别 · 倒排索引，负责关键词与实体匹配'),
        ('个性化推荐 —— ', '协同过滤 / 基于内容的推荐（后续演进）'),
        ('人工反馈闭环 —— ', '维护后台标注（标记正确 / 编辑）反哺语料与提示词'),
        ('算力投入 —— ', '训练 + 推理服务器约 2 万元/月（开发说明估算），需用量监控'),
    ], size=11.5, sa=13)
    note(slide, '算法采用 LLM 加 Agent 架构：中枢大模型选 LLAMA 和 GLM，'
                '用 MSAgent-Bench 工具指令数据集微调增强任务规划与调度，'
                '同时结合讯飞星火 API。回答生成走 RAG 思想——先从招投标知识库检索，'
                '再生成带来源的回答，从机制上压低幻觉；传统 NLP 负责分词、'
                '实体识别与倒排检索。本页只讲思想，模型与训练细节由算法文档承载。')
    return slide


def s13_data(prs):
    slide = deck(prs, '技术篇 · 04', '数据资产与数据模型', 13, '数据卡片 + ER 简图')
    chip(slide, 0.62, 1.66, 4.2, 0.42, '数据资产 · 六大信息域', fill=NAVY, size=12)
    domains = [
        ('政策信息', '4 字段'), ('招标信息', '20+ 字段（最丰富）'), ('舆情信息', '4 字段'),
        ('企业信息', '19 字段'), ('价格信息', '12 字段'), ('商品信息', '12 字段'),
    ]
    for i, (t, d) in enumerate(domains):
        dx = 0.62 + (i % 3) * 2.04
        dy = 2.22 + (i // 3) * 1.48
        box(slide, dx, dy, 1.90, 1.30,
            [{'t': t, 's': 12.5, 'b': True, 'c': NAVY, 'sa': 4},
             {'t': d, 's': 9.5, 'c': GRAY}], fill=LIGHT, line=SKY)
    chip(slide, 7.00, 1.66, 3.4, 0.42, '数据模型 · 实体关系', fill=BLUE, size=12)
    for i, t in enumerate(['用户', '问题', '答案']):
        box(slide, 7.10 + i * 1.98, 2.30, 1.45, 0.62,
            [{'t': t, 's': 12.5, 'b': True, 'c': WHITE}], fill=NAVY)
        if i < 2:
            arrow(slide, 8.62 + i * 1.98, 2.45, 0.40, 0.32, fill=BLUE)
            text(slide, 8.52 + i * 1.98, 2.06, 0.7, 0.25,
                 [{'t': '1 : N', 's': 9, 'b': True, 'c': BLUE, 'a': C}])
    bullets(slide, 7.00, 3.30, 5.70, 3.5, [
        ('实体 —— ', '用户（用户名/密码/邮箱）· 问题（标题/描述/时间）· 答案（内容/类型/时间）'),
        ('现状① —— ', '标的物结构化数据 8,790 行 × 17 字段（项目编号/采购人/代理机构/预算/中标人/中标金额…）'),
        ('现状② —— ', '政策实务问答对 82 条（单一来源 · 质疑异议等）'),
        ('覆盖全流程 —— ', '招标域字段：招标计划 → 中标结果 → 合同履约'),
    ], size=11, sa=12)
    note(slide, '数据资产分两块：结构化域数据按六大信息域建字段模型，'
                '招标域最丰富，20 多个字段覆盖从招标计划到合同履约的全流程；'
                '知识语料已有 82 条政策实务问答对作为质量基线。'
                '实体模型很简洁：用户、问题、答案三个实体、两组一对多关系，'
                '正好支撑后台列表的八个列。')
    return slide


def s14_engineering(prs):
    slide = deck(prs, '工程篇 · 01', '工程化与质量保障', 14, '研发流水线图')
    steps = [
        ('禅道', '需求 · 任务 · 缺陷跟踪', LIGHT, DARK),
        ('GitLab', '分支 · MR · Code Review', LIGHT, DARK),
        ('Jenkins', 'lint · test · build', LIGHT, DARK),
        ('测试环境', 'E2E 冒烟 · 种子数据', LIGHT, DARK),
        ('生产环境', '手动确认 · 可回滚', NAVY, WHITE),
    ]
    x = 0.72
    for i, (t, d, f, c) in enumerate(steps):
        box(slide, x, 1.90, 2.10, 1.05,
            [{'t': t, 's': 13, 'b': True, 'c': c, 'sa': 3},
             {'t': d, 's': 9, 'c': (GRAY if f == LIGHT else WHITE)}], fill=f, line=SKY)
        if i < 4:
            arrow(slide, x + 2.13, 2.28, 0.30, 0.34, fill=BLUE)
        x += 2.45
    chip(slide, 0.72, 3.35, 3.3, 0.44, '质量门禁（MR 必检）', fill=BLUE, size=12)
    left_items = [
        ('TypeScript strict —— ', '全量开启，禁用裸 any'),
        ('风格统一 —— ', 'ESLint + Prettier + Stylelint'),
        ('单元测试 —— ', 'Vitest 覆盖工具层 · 状态流转 · 校验'),
    ]
    right_items = [
        ('E2E —— ', 'Playwright 用例 = 验收标准 AC 编号，冒烟进 CI'),
        ('体积预算 —— ', '首屏 JS ≤ 500KB(gzip)，超预算 CI 失败'),
        ('契约先行 —— ', 'OpenAPI 生成 TS 类型，改契约先改文档'),
    ]
    bullets(slide, 0.72, 3.98, 5.85, 2.2, left_items, size=11.5, sa=12)
    bullets(slide, 6.90, 3.98, 5.80, 2.2, right_items, size=11.5, sa=12)
    box(slide, 0.72, 6.25, 11.98, 0.60,
        [{'t': '环境分离：dev / test / prod 三套配置　·　生产部署人工确认，保留最近 N 版可回滚',
          's': 11.5, 'b': True, 'c': DARK}], fill=PALE, line=SKY)
    note(slide, '工程链路沿用开发说明指定的禅道、GitLab、Jenkins。'
                '质量保障的核心思路是把验收标准脚本化：Playwright 用例直接对应'
                '开发文档的 AC 编号，每次合并请求自动跑冒烟；'
                '包体积设置预算，超了 CI 直接失败——性能不靠自觉，靠门禁。'
                '生产部署保留人工确认环节，且支持版本回滚。')
    return slide


def s15_quality(prs):
    slide = deck(prs, '工程篇 · 02', '性能 · 安全 · 可访问性', 15, '三支柱 + 埋点链路')
    cards = [
        ('性能', NAVY, [
            '首屏可交互 ≤ 2s（常规网络）',
            '回答首字 ≤ 3s（依赖算法服务）',
            '首屏 JS ≤ 500KB(gzip)',
            '后台长列表分页 + 虚拟滚动',
            '（指标为建议基线，联调后确认）',
        ]),
        ('安全', ORANGE, [
            'JWT 鉴权 + 全站 HTTPS',
            'AI 回答渲染 XSS 消毒（DOMPurify）',
            '前后端双重权限校验',
            '敏感信息脱敏（联系人/方式）',
            '依赖审计：npm audit + 锁文件',
        ]),
        ('可访问性', GREEN, [
            '键盘全流程（Enter 发送 / Shift+Enter 换行）',
            '对比度 ≥ 4.5:1（WCAG 2.1 AA）',
            'aria-live 感知回答更新',
            '弹窗焦点圈定与返还',
            'E2E 含纯键盘路径用例',
        ]),
    ]
    x = 0.62
    for t, color, items in cards:
        box(slide, x, 1.72, 4.00, 0.55, [{'t': t, 's': 14, 'b': True, 'c': WHITE}], fill=color)
        paras = [{'t': '▪ ' + it, 's': 10.5, 'c': DARK, 'sa': 8, 'a': L} for it in items]
        box(slide, x, 2.27, 4.00, 3.30, paras, fill=PALE, line=SKY, align=L,
            anchor=MSO_ANCHOR.TOP)
        x += 4.25
    box(slide, 0.62, 5.85, 12.09, 0.90,
        [{'t': '埋点（PRD 定义）', 's': 10.5, 'b': True, 'c': SKY, 'sa': 3},
         {'t': '点击「发送」按钮 → 事件名「发送」按钮 · 属性「页面点击」· 值「次数」 → 上报统计分析，支撑运营决策',
          's': 12.5, 'b': True, 'c': WHITE}], fill=NAVY)
    note(slide, '三个非功能维度：性能上定了可量化基线——首屏两秒、首字三秒、'
                '首屏 JS 五百 K，全部进 CI 门禁；安全上最特别的是 AI 回答渲染必须消毒，'
                '模型输出同样是不可信输入，用 DOMPurify 白名单处理；'
                '可访问性按 WCAG 2.1 AA，键盘全流程是硬要求。'
                '底部的埋点是 PRD 明确定义的第一批事件，直接服务统计分析模块。')
    return slide


def s16_plan(prs):
    slide = deck(prs, '计划篇 · 01', '里程碑与风险', 16, '时间轴 + 风险应对表')
    bar(slide, 0.90, 2.62, 11.50, 0.05, BLUE)
    ms = [
        ('M0 需求分析', 'W1–2', '文档评审通过'),
        ('M1 设计', 'W3–4', 'UI 与契约定稿'),
        ('M2 开发Ⅰ', 'W5–8', 'C端主流程可演示'),
        ('M3 开发Ⅱ', 'W9–12', '全功能可演示'),
        ('M4 测试', 'W13–14', 'P0 缺陷清零'),
        ('M5 上线', 'W15', '验收上线'),
    ]
    for i, (name, wk, exit_) in enumerate(ms):
        cx = 1.40 + i * 2.20
        d = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - 0.10),
                                   Inches(2.52), Inches(0.22), Inches(0.22))
        d.fill.solid()
        d.fill.fore_color.rgb = NAVY if i < 5 else ORANGE
        d.line.color.rgb = WHITE
        d.line.width = Pt(1.5)
        d.shadow.inherit = False
        text(slide, cx - 1.00, 2.02, 2.00, 0.3,
             [{'t': name, 's': 11.5, 'b': True, 'c': NAVY, 'a': C}])
        text(slide, cx - 1.00, 2.86, 2.00, 0.55,
             [{'t': wk, 's': 10, 'b': True, 'c': BLUE, 'a': C, 'sa': 1},
              {'t': exit_, 's': 9, 'c': MUTE, 'a': C}])
    risks = [
        ('智能回答准确性不达预期', '高', '维护闭环兜底；82 条问答基线；持续扩充语料'),
        ('第三方数据源页面/接口变更', '高', '采集监控告警；解析规则配置化快速适配'),
        ('大模型算力成本（约 2 万元/月）', '中', '用量监控与预算告警；模型按场景分档'),
        ('设计稿信息缺口（登录页/枚举值）', '中', 'M1 阶段补齐视觉稿，假设清单逐条确认'),
        ('范围蔓延（API / 多端提前介入）', '中', '以范围基线做变更控制，走正式变更流程'),
    ]
    tbl_shape = slide.shapes.add_table(6, 3, Inches(0.62), Inches(3.80),
                                       Inches(12.09), Inches(2.40))
    tbl = tbl_shape.table
    tbl.first_row = True
    tbl.columns[0].width = Inches(4.10)
    tbl.columns[1].width = Inches(0.90)
    tbl.columns[2].width = Inches(7.09)
    for i in range(6):
        tbl.rows[i].height = Inches(0.40)
    for j, h in enumerate(['风险', '等级', '应对措施']):
        set_cell(tbl.cell(0, j), h, size=11, bold=True, color=WHITE, fill=NAVY)
    for i, (r, lv, a) in enumerate(risks):
        set_cell(tbl.cell(i + 1, 0), r, size=10.5, fill=PALE if i % 2 == 0 else WHITE, align=L)
        set_cell(tbl.cell(i + 1, 1), lv, size=10.5, bold=True,
                 color=RED if lv == '高' else ORANGE,
                 fill=PALE if i % 2 == 0 else WHITE)
        set_cell(tbl.cell(i + 1, 2), a, size=10.5, fill=PALE if i % 2 == 0 else WHITE, align=L)
    text(slide, 0.62, 6.30, 12.09, 0.3,
         [{'t': '注：里程碑周期为估算（约 15 周，假设），以项目启动会确认为准；风险详情见《开发文档.md》§9。',
           's': 9.5, 'c': MUTE, 'a': C}])
    note(slide, '计划五阶段、约十五周：M2 结束 C 端主流程可演示、M3 结束全功能可演示，'
                '是两个关键检查点。风险 Top5 如表——最需要管理的是回答准确性，'
                '我们的答案是维护闭环兜底加问答基线；其次是设计稿缺口，M1 阶段集中补齐。'
                '需要说明：周期是估算值，以项目启动会确认为准。')
    return slide


def s17_summary(prs):
    slide = deck(prs, '计划篇 · 02', '总结与展望', 17, '成果清单 + 演进路线图')
    chip(slide, 0.62, 1.66, 2.6, 0.44, '一期交付', fill=NAVY, size=12.5)
    bullets(slide, 0.62, 2.26, 6.30, 2.4, [
        ('C 端对话式问答 —— ', '结构化回答 · 来源可溯 · 埋点接入'),
        ('B 端维护后台 —— ', '六条件筛选 · 三类维护操作 · 操作留痕'),
        ('六大信息域数据底座 —— ', '采集 · 解析 · 结构化入库'),
        ('质量与工程基座 —— ', '类型安全 · 测试门禁 · 监控埋点'),
    ], size=11.5, sa=11)
    text(slide, 0.62, 4.60, 3.0, 0.3, [{'t': '项目价值', 's': 12, 'b': True, 'c': BLUE}])
    for i, v in enumerate(['节约人工成本', '提升信息精确性', '决策科学依据']):
        box(slide, 0.62 + i * 2.10, 4.95, 1.98, 0.52,
            [{'t': v, 's': 11.5, 'b': True, 'c': NAVY}], fill=LIGHT, line=SKY)
    chip(slide, 7.30, 1.66, 2.6, 0.44, '演进路线', fill=BLUE, size=12.5)
    evo = [
        ('标准 API 开放', '信息数据接口接入企业（PRD 规划）'),
        ('移动端与多端覆盖', '移动 Web / 客户端 / 小程序'),
        ('个性化推荐', '协同过滤 · 用户画像（开发说明规划）'),
        ('知识图谱 · 多模态', '复杂推理 · 图文问答（远期）'),
    ]
    y = 2.26
    for i, (t, d) in enumerate(evo):
        f = NAVY if i == 3 else LIGHT
        c = WHITE if i == 3 else DARK
        box(slide, 7.30, y, 5.40, 0.72,
            [{'t': t, 's': 12, 'b': True, 'c': (WHITE if i == 3 else NAVY), 'sa': 1, 'a': L},
             {'t': d, 's': 9, 'c': (WHITE if i == 3 else GRAY), 'a': L}],
            fill=f, line=SKY, align=L)
        if i < 3:
            arrow(slide, 9.85, y + 0.76, 0.30, 0.24, fill=BLUE, direction='d')
        y += 1.06
    box(slide, 0.62, 6.35, 12.09, 0.60,
        [{'t': '请评审重点：假设清单（开发文档附录 10.1） · 里程碑节奏 · 验收标准',
          's': 13, 'b': True, 'c': WHITE}], fill=NAVY)
    note(slide, '总结：一期交付"两端一底座"——C 端问答、B 端维护、'
                '六大信息域数据底座，价值指向节约人工成本、提升信息获取精确性。'
                '后续沿标准 API 开放、移动端、个性化推荐、知识图谱演进。'
                '请各位重点评审假设清单、里程碑节奏与验收标准，谢谢。')
    return slide


def main():
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)
    s01_cover(prs)
    s02_agenda(prs)
    s03_background(prs)
    s04_users(prs)
    s05_features(prs)
    s06_flow(prs)
    s07_page_chat(prs)
    s08_page_admin(prs)
    s09_interaction(prs)
    s10_arch(prs)
    s11_stack(prs)
    s12_algo(prs)
    s13_data(prs)
    s14_engineering(prs)
    s15_quality(prs)
    s16_plan(prs)
    s17_summary(prs)
    prs.core_properties.title = '招投标智能问答机器人 · 产品设计与技术架构'
    prs.core_properties.author = '前端架构组'
    out = 'D:/rag_agent/docs/产品设计与技术架构.pptx'
    prs.save(out)
    print('saved:', out, '| slides:', len(prs.slides))


if __name__ == '__main__':
    main()
