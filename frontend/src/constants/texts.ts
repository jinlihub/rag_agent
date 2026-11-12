/** 文案集中管理（开发文档 §6.4），后续可平移到 vue-i18n 语言包 */
export const TEXTS = {
  appTitle: '招投标问答机器人',
  botName: '信息官',

  emptyQuestion: '请输入您的问题',
  genFailed: '回答生成失败，请点击重试',
  genTimeout: '回答生成超时，请重试',
  netError: '网络异常，请检查网络后重试',
  adminListEmpty: '暂无符合条件的问答记录',
  clusterListEmpty: '暂无可处理的聚类，请先运行 scripts/cluster_unmaintained.py',
  confirmApproveCluster: '确定将该簇内全部问题置为"已维护"吗？',

  attachImage: '上传图片',
  parsingImage: '正在解析图片…',
  parseFailed: '图片解析失败，请重试',

  markCorrectDone: '已标记正确',
  saveDone: '保存成功',
  noNeedDone: '已标记为不需要维护',
  confirmNoNeed: '确定将该条标记为"不需要维护"吗？',
  answerRequired: '回答内容不能为空',

  welcome: '您好，我是招投标信息官，请输入您的问题',
} as const

/** Agent 工具名 → 展示文案 */
export const TOOL_LABELS: Record<string, string> = {
  search_bidding_knowledge: '招投标知识库',
  search_knowledge_graph: '知识图谱',
  search_postgresql: '中标数据库',
  graph_query: '交易图谱',
  search_web: '联网搜索（Tavily）',
  search_web_exa: '联网搜索（Exa）',
}

/** 用时统计的阶段 key → 展示文案（工具类走 TOOL_LABELS） */
export const STAGE_LABELS: Record<string, string> = {
  history: '历史压缩',
  routing: '意图路由',
  analysis: '意图分析',
  generating: '生成回答',
}

/** 来源 kind → 展示文案 */
export const SOURCE_LABELS: Record<string, string> = {
  web: '网页',
  bid_subject: '中标记录',
  knowledge: '知识库',
  legal: '法规条文',
  policy: '政策文件',
  faq: '实务问答',
  graph: '知识图谱',
}
