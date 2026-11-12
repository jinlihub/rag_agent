/** 与后端 OpenAPI 契约对齐的类型定义（技术栈.md #2） */

export interface User {
  id: number
  username: string
  display_name: string
  user_type: string
  role: 'admin' | 'user'
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

/** 来源引用（runner.collect_sources 产出；web = 联网搜索结果） */
export interface SourceItem {
  kind: string
  title: string
  publish_time?: string
  award_time?: string
  award_amount_wan?: number
  province?: string
  city?: string
  law_type?: string
  score?: number
  url?: string
}

/** 问答各阶段耗时（timing 事件；key: history | routing | analysis | tool | generating） */
export interface TimingStage {
  key: string
  seconds: number
  /** key = 'tool' 时的工具名，展示时映射 TOOL_LABELS */
  tool?: string
}

export type MaintainStatus = '未维护' | '已维护' | '不需要维护'

/** B 端问答记录（设计稿 p12 列结构） */
export interface QaRecord {
  id: number
  question: string
  answer: string | null
  maintain_status: MaintainStatus
  result_evaluation: string
  created_at: string
  updated_at: string
  username: string
  display_name: string
  user_type: string
}

export interface QaListParams {
  username?: string
  keyword?: string
  user_type?: string
  maintain_status?: string
  result_evaluation?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}

export interface QaListResult {
  total: number
  page: number
  page_size: number
  items: QaRecord[]
}

/** 未维护问题聚类（GET /api/admin/clusters；草稿由 cluster_unmaintained.py 离线写入） */
export interface QaCluster {
  /** 簇 id = 簇内最小 qa_record.id（脚本重跑后保持稳定） */
  id: number
  /** 簇内问题条数 */
  size: number
  /** 同簇共用的回答草稿 */
  draft: string
  /** 问题样例（最多 5 条） */
  questions: string[]
  qa_ids: number[]
}

export interface QaClusterResult {
  /** 簇数 */
  total: number
  /** 已起草的未维护问题总条数 */
  total_questions: number
  items: QaCluster[]
}

/** 系统监控（GET /api/admin/system，指标值为字节/百分比的原生数值） */
export interface CpuMetrics {
  percent: number
  per_core: number[]
  logical: number
  physical: number
}

export interface MemoryMetrics {
  total: number
  used: number
  available: number
  percent: number
}

export interface SwapMetrics {
  total: number
  used: number
  percent: number
}

export interface DiskPartition {
  device: string
  mountpoint: string
  fstype: string
  total: number
  used: number
  free: number
  percent: number
}

export interface DiskMetrics extends Omit<DiskPartition, 'device' | 'mountpoint' | 'fstype'> {
  path: string
  partitions: DiskPartition[]
}

export interface GpuItem {
  index: number | null
  name: string
  utilization: number | null
  memory_used: number | null
  memory_total: number | null
  temperature: number | null
}

export interface GpuMetrics {
  available: boolean
  message: string
  items: GpuItem[]
}

export interface HostMetrics {
  hostname: string
  platform: string
  python: string
  boot_time: string
  uptime_seconds: number
  load_avg: number[] | null
}

export interface ProcessMetrics {
  pid: number
  name: string
  cpu_percent: number
  memory_rss: number
  memory_percent: number
  threads: number
  create_time: string
  uptime_seconds: number
}

export interface SystemLogEntry {
  time: string
  level: string
  logger: string
  message: string
}

export interface SystemMetrics {
  timestamp: string
  host: HostMetrics
  cpu: CpuMetrics
  memory: MemoryMetrics
  swap: SwapMetrics
  disk: DiskMetrics
  gpu: GpuMetrics
  process: ProcessMetrics
  logs: SystemLogEntry[]
}

/** /api/chat 的 SSE 事件（runner.py 事件契约） */
export type SseEvent =
  | { type: 'meta'; qa_id: number; /** 本次回答实际使用的模型 id */ model?: string }
  | {
      type: 'status'
      stage: 'thinking' | 'analysis' | 'quality' | 'tool_call' | 'generating'
      tool?: string
      args?: unknown
      /** ReAct 每轮的分析文本（stage = analysis）或质量改进建议（stage = quality） */
      text?: string
      /** 结果质量判定（stage = quality 时）：empty | weak | error */
      verdict?: string
    }
  | { type: 'sources'; items: SourceItem[] }
  /** 图表：spec 为后端代码生成的 ECharts option；前端校验失败时静默忽略 */
  | { type: 'chart'; spec: Record<string, unknown> }
  /** 主动澄清：ask_user 被调用后立即结束，options 为可点击发送的候选问句 */
  | { type: 'clarify'; question: string; options: string[] }
  | { type: 'timing'; stages: TimingStage[]; /** 总用时（秒），已含历史构建 */ total: number }
  | { type: 'delta'; text: string }
  /** 深度思考过程增量（开关开启且模型返回 reasoning_content 时） */
  | { type: 'reasoning'; text: string }
  | { type: 'error'; message: string }
  | { type: 'done' }

/** C 端历史会话（GET /api/history/sessions） */
export interface HistorySession {
  session_id: string
  title: string
  count: number
  last_time: string
}

/** 历史会话消息（GET /api/history/sessions/{id}，user/assistant 交替） */
export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceItem[]
  time: string
  /** assistant 消息：问答记录 id，用于反馈点赞/点踩 */
  qa_id?: number
  /** assistant 消息：已保存的结果评价（赞/踩/无） */
  rating?: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceItem[]
  streaming?: boolean
  failed?: boolean
  qaId?: number
  /** 用户反馈的结果评价：赞 / 踩；undefined = 未反馈 */
  rating?: string
  /** 用户消息附带的图片（本地预览 URL，图片解析流） */
  image?: string
  /** 原始图片文件，仅供失败重试用，不参与渲染与传输 */
  imageFile?: File
  /** 各阶段耗时明细（timing 事件；历史恢复的旧消息没有此数据） */
  timing?: TimingStage[]
  /** 总用时（秒） */
  totalSeconds?: number
  /** 深度思考过程原文（reasoning 事件；不落库，历史恢复的旧消息没有） */
  reasoning?: string
  /** 思考过程面板是否展开（流式时展开，正文开始后自动收起） */
  reasoningOpen?: boolean
  /** 图表 spec（chart 事件；不落库，历史恢复的旧消息没有） */
  chart?: Record<string, unknown>
  /** 主动澄清（clarify 事件；不落库，历史恢复的旧消息没有） */
  clarify?: { question: string; options: string[] }
}
