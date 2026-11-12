<script setup lang="ts">
import { ArrowDown, ArrowUp, Clock, Close, Cpu, Loading, MoreFilled, Paperclip, Plus, Search } from '@element-plus/icons-vue'
import DOMPurify from 'dompurify'
import * as echarts from 'echarts'
import { marked } from 'marked'
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import type { PropType } from 'vue'
import { useRouter } from 'vue-router'

import { streamChat } from '@/api/chat'
import { fetchModels, getSelectedModel, setSelectedModel } from '@/api/models'
import type { ChatModel } from '@/api/models'
import { deleteAllSessions, deleteHistorySession, fetchHistorySessions, fetchSessionMessages, setQaEvaluation } from '@/api/history'
import { errMsg } from '@/api/http'
import { getSessionId, rotateSessionId, trackSendClick } from '@/api/track'
import { parseImage } from '@/api/vision'
import { SOURCE_LABELS, STAGE_LABELS, TEXTS, TOOL_LABELS } from '@/constants/texts'
import { useAuthStore } from '@/stores/auth'
import type { ChatMessage, HistoryMessage, HistorySession } from '@/types'

const router = useRouter()
const auth = useAuthStore()

const EXAMPLES = [
  '近半年安徽合肥区域有哪些企业中标？',
  '供应商提出质疑的时限是多少天？',
  '最新的关于 EPC 项目的计划信息？',
  '有哪些关于空调的采购?',
  '采购最多的标的是什么?',
  '空调的供应商和采购人有哪些?',
] as const

/** 与后端 /api/vision/parse 的限制保持一致 */
const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const MAX_IMAGE_BYTES = 5 * 1024 * 1024

/** chart 事件的最小合法性检查：spec 必须是带非空 series 的对象 */
function isValidChartSpec(spec: unknown): spec is Record<string, unknown> {
  if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return false
  const series = (spec as Record<string, unknown>).series
  return (
    Array.isArray(series) &&
    series.length > 0 &&
    series.every(
      (s) => !!s && typeof s === 'object' && typeof (s as Record<string, unknown>).type === 'string',
    )
  )
}

/** 单条回答的图表块：spec 由后端生成，渲染失败时静默忽略，不影响文字回答 */
const ChartBlock = defineComponent({
  name: 'AnswerChart',
  props: {
    spec: { type: Object as PropType<Record<string, unknown>>, required: true },
  },
  setup(props) {
    const el = ref<HTMLElement>()
    let chart: echarts.ECharts | null = null
    let resizeObserver: ResizeObserver | null = null
    const render = () => {
      if (!el.value) return
      try {
        if (!chart) chart = echarts.init(el.value)
        chart.setOption(props.spec as echarts.EChartsOption, true)
      } catch {
        // spec 非法或渲染失败：保留文字回答，不向用户抛错
      }
    }
    const onResize = () => chart?.resize()
    onMounted(() => {
      render()
      // 回答卡片会随正文流式增长，图表容器宽度变化时同步画布尺寸
      if (el.value && typeof ResizeObserver !== 'undefined') {
        resizeObserver = new ResizeObserver(onResize)
        resizeObserver.observe(el.value)
      }
      window.addEventListener('resize', onResize)
    })
    watch(() => props.spec, render, { deep: true })
    onBeforeUnmount(() => {
      resizeObserver?.disconnect()
      window.removeEventListener('resize', onResize)
      chart?.dispose()
      chart = null
    })
    return () => h('div', { ref: el, class: 'answer-chart' })
  },
})

const messages = ref<ChatMessage[]>([])
const input = ref('')
const sending = ref(false)
const activeTool = ref('')
const listRef = useTemplateRef<HTMLElement>('listRef')
const pendingImage = ref<{ file: File; url: string } | null>(null)
const fileRef = useTemplateRef<HTMLInputElement>('fileRef')
/** 联网搜索开关（持久化；默认关闭，开启后 Agent 必查本地知识库+联网搜索） */
const webSearch = ref(localStorage.getItem('rag_web_search') === '1')

function toggleWebSearch() {
  webSearch.value = !webSearch.value
  localStorage.setItem('rag_web_search', webSearch.value ? '1' : '0')
}

/** 深度思考开关（持久化；开启后最终作答调高思考强度，工具检索轮次不变） */
const deepThinking = ref(localStorage.getItem('rag_deep_thinking') === '1')

function toggleDeepThinking() {
  deepThinking.value = !deepThinking.value
  localStorage.setItem('rag_deep_thinking', deepThinking.value ? '1' : '0')
}

// ── LLM 选择（回答文本问题所用模型；空串 = 跟随后端默认）────────────────────
const modelItems = ref<ChatModel[]>([])
const modelDefault = ref('')
const selectedModel = ref(getSelectedModel())

const currentModelLabel = computed(
  () => modelItems.value.find((m) => m.id === selectedModel.value)?.id ?? '默认',
)

const currentModelTip = computed(() =>
  selectedModel.value
    ? `回答模型：${selectedModel.value}`
    : `回答模型：默认（${modelDefault.value || '服务端配置'}），点击切换`,
)

let modelProbeRetries = 0

/** 拉取候选模型清单；后端异步探活，available=null 时隔几秒重取几次拿到置灰结论 */
async function loadModels() {
  try {
    const data = await fetchModels()
    modelDefault.value = data.default
    modelItems.value = data.items
    // 本地记住的模型已不在候选清单（服务端配置变更）时清掉，避免每次提问都 400
    if (selectedModel.value && !data.items.some((m) => m.id === selectedModel.value)) {
      selectedModel.value = ''
      setSelectedModel('')
    }
    if (modelProbeRetries < 6 && data.items.some((m) => m.available === null)) {
      modelProbeRetries += 1
      window.setTimeout(() => void loadModels(), 5000)
    }
  } catch {
    /* 清单加载失败不影响问答主流程，但仍重试几次：后端 --reload 重启的几百毫秒内会连不上，
       若不重试则 modelItems 永远为空，下拉一直停在"加载中" */
    if (modelProbeRetries < 6) {
      modelProbeRetries += 1
      window.setTimeout(() => void loadModels(), 5000)
    }
  }
}

function onModelCommand(id: string) {
  if (id === selectedModel.value) return
  selectedModel.value = id
  setSelectedModel(id)
  ElMessage.success(`回答模型已切换为 ${id}`)
}

// ── 对话内容搜索（Ctrl+F 式，仅当前窗口；跨会话搜索见历史抽屉）──────────────
// 思路：直接在对话 DOM 的文本节点里定位关键词并包 <mark>（Markdown 源文的偏移
// 与渲染后文本不一致，从渲染结果侧搜索才准确）；命中列表非响应式引用元素。
const searchOpen = ref(false)
const searchKeyword = ref('')
const searchInputRef = useTemplateRef<{ focus: () => void }>('searchInputRef')
const searchHits = ref<HTMLElement[]>([])
const searchCurrent = ref(0) // 1-based；0 = 无命中
let searchTimer: number | undefined

const searchCountText = computed(() => {
  if (!searchKeyword.value.trim()) return ''
  return searchHits.value.length ? `${searchCurrent.value}/${searchHits.value.length}` : '无匹配'
})

/** 移除全部高亮标记并合并回原文本节点 */
function clearHighlights() {
  listRef.value?.querySelectorAll('mark.search-hit').forEach((m) => {
    const parent = m.parentNode
    if (!parent) return
    parent.replaceChild(document.createTextNode(m.textContent ?? ''), m)
    parent.normalize()
  })
}

/** 扫描对话区文本节点，把命中片段包进 <mark class="search-hit"> */
function applyHighlights() {
  clearHighlights()
  searchHits.value = []
  const kw = searchKeyword.value.trim().toLowerCase()
  const root = listRef.value
  if (!kw || !root) return
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!(node.nodeValue ?? '').trim()) return NodeFilter.FILTER_REJECT
      const p = node.parentElement
      return p && p.closest('mark.search-hit') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT
    },
  })
  const targets: Text[] = []
  for (let n = walker.nextNode(); n; n = walker.nextNode()) targets.push(n as Text)
  const hits: HTMLElement[] = []
  for (const node of targets) {
    const text = node.nodeValue ?? ''
    const lower = text.toLowerCase()
    if (!lower.includes(kw)) continue
    const parent = node.parentNode
    if (!parent) continue
    const frag = document.createDocumentFragment()
    let pos = 0
    for (let i = lower.indexOf(kw); i >= 0; i = lower.indexOf(kw, pos)) {
      frag.appendChild(document.createTextNode(text.slice(pos, i)))
      const mark = document.createElement('mark')
      mark.className = 'search-hit'
      mark.textContent = text.slice(i, i + kw.length)
      frag.appendChild(mark)
      hits.push(mark)
      pos = i + kw.length
    }
    frag.appendChild(document.createTextNode(text.slice(pos)))
    parent.replaceChild(frag, node)
  }
  searchHits.value = hits
}

/** 定位到某个命中（滚动 + 当前态） */
function focusHit(index: number) {
  searchHits.value.forEach((m) => m.classList.remove('active'))
  const el = searchHits.value[index]
  if (!el) return
  el.classList.add('active')
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

/** 关键词输入（防抖 250ms）后重建索引并跳到第一条 */
function runSearch() {
  applyHighlights()
  searchCurrent.value = searchHits.value.length ? 1 : 0
  if (searchCurrent.value) focusHit(0)
}

function onSearchInput() {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(runSearch, 250)
}

/** 上/下一个命中（循环） */
function stepSearch(dir: 1 | -1) {
  const total = searchHits.value.length
  if (!total) return
  searchCurrent.value = ((searchCurrent.value - 1 + dir + total) % total) + 1
  focusHit(searchCurrent.value - 1)
}

/** 消息增删或内容落定后重建索引：保持当前序号，不主动滚动 */
async function refreshSearch() {
  if (!searchOpen.value || !searchKeyword.value.trim()) return
  await nextTick()
  applyHighlights()
  if (searchCurrent.value > searchHits.value.length) searchCurrent.value = searchHits.value.length
  if (searchCurrent.value) searchHits.value[searchCurrent.value - 1]?.classList.add('active')
}

function toggleSearch(open?: boolean) {
  searchOpen.value = open ?? !searchOpen.value
  if (searchOpen.value) {
    void nextTick(() => searchInputRef.value?.focus())
    if (searchKeyword.value.trim()) void refreshSearch()
    else {
      searchHits.value = []
      searchCurrent.value = 0
    }
  } else {
    clearHighlights()
    searchHits.value = []
    searchCurrent.value = 0
  }
}

function onSearchKeydown(e: Event | KeyboardEvent) {
  if (!(e instanceof KeyboardEvent)) return
  if (e.key === 'Enter') {
    e.preventDefault()
    stepSearch(e.shiftKey ? -1 : 1)
  } else if (e.key === 'Escape') {
    toggleSearch(false)
  }
}

/** Ctrl/Cmd+F 打开对话内搜索（接管浏览器查找），Esc 关闭 */
function onGlobalKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
    e.preventDefault()
    toggleSearch(true)
  } else if (e.key === 'Escape' && searchOpen.value) {
    toggleSearch(false)
  }
}

watch(
  () => messages.value.length,
  () => void refreshSearch(),
)

// ── 对话历史（跨会话恢复 + 搜索）───────────────────────────────────────────
const historyOpen = ref(false)
const historyKeyword = ref('')
const historySessions = ref<HistorySession[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyLoading = ref(false)

/** 历史消息 → 聊天消息（恢复用） */
function toChatMessages(list: HistoryMessage[]): ChatMessage[] {
  return list.map((m) =>
    m.role === 'user'
      ? { role: 'user', content: m.content }
      : {
          role: 'assistant',
          content: m.content,
          sources: m.sources,
          qaId: m.qa_id,
          rating: m.rating && m.rating !== '无' ? m.rating : undefined,
        },
  )
}

/** 跨会话恢复：进入页面自动载入当前会话的历史（新会话/无记录时静默保持空会话） */
onMounted(async () => {
  window.addEventListener('keydown', onGlobalKey)
  modelProbeRetries = 0 // 每次进入页面重置重试计数，避免上次耗尽后再不重试
  void loadModels()
  try {
    const data = await fetchSessionMessages(getSessionId())
    if (data.messages.length) {
      messages.value = toChatMessages(data.messages)
      void scrollBottom()
    }
  } catch {
    /* 无历史（404） */
  }
})

/** 开启新会话：轮换会话 ID 并清空窗口，旧会话留在历史里 */
function newChat() {
  if (sending.value) return
  rotateSessionId()
  messages.value = []
  input.value = ''
}

async function openHistory() {
  historyOpen.value = true
  historyKeyword.value = ''
  historyPage.value = 1
  historySessions.value = []
  await loadHistory()
}

async function loadHistory(append = false) {
  historyLoading.value = true
  try {
    const data = await fetchHistorySessions({
      keyword: historyKeyword.value.trim() || undefined,
      page: historyPage.value,
      page_size: 20,
    })
    historyTotal.value = data.total
    historySessions.value = append ? [...historySessions.value, ...data.items] : data.items
  } catch (e) {
    ElMessage.error(errMsg(e, '历史加载失败'))
  } finally {
    historyLoading.value = false
  }
}

function searchHistory() {
  historyPage.value = 1
  void loadHistory()
}

function loadMoreHistory() {
  historyPage.value += 1
  void loadHistory(true)
}

/** 恢复某个历史会话到聊天窗口；当前会话 ID 切到该会话，后续提问接续 */
async function restoreSession(s: HistorySession) {
  if (sending.value) return
  try {
    const data = await fetchSessionMessages(s.session_id)
    localStorage.setItem('rag_session', s.session_id)
    messages.value = toChatMessages(data.messages)
    historyOpen.value = false
    void refreshSearch()
    void scrollBottom()
  } catch (e) {
    ElMessage.error(errMsg(e, '会话加载失败'))
  }
}

/** 删除整组历史对话；删的是当前会话时，清空窗口并轮换新会话 */
async function removeSession(s: HistorySession) {
  try {
    await deleteHistorySession(s.session_id)
    historySessions.value = historySessions.value.filter((x) => x.session_id !== s.session_id)
    historyTotal.value = Math.max(0, historyTotal.value - 1)
    ElMessage.success('会话已删除')
    if (getSessionId() === s.session_id) {
      rotateSessionId()
      messages.value = []
    }
  } catch (e) {
    ElMessage.error(errMsg(e, '删除失败'))
  }
}

/** 清空全部对话：二次确认后删除当前用户全部问答记录，清空窗口并轮换会话 */
async function removeAllSessions() {
  if (sending.value) return
  try {
    await ElMessageBox.confirm('将删除你的全部对话记录，删除后不可恢复。确定继续吗？', '清空全部对话', {
      type: 'warning',
      confirmButtonText: '全部删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await deleteAllSessions()
    historySessions.value = []
    historyTotal.value = 0
    historyOpen.value = false
    rotateSessionId()
    messages.value = []
    void refreshSearch()
    ElMessage.success('对话记录已全部删除')
  } catch (e) {
    ElMessage.error(errMsg(e, '删除失败'))
  }
}

/** 判断一行是否为 Markdown 表格分隔行（| --- | :---: | 形态） */
function isTableSeparator(line: string): boolean {
  return /\|/.test(line) && line.includes('-') && /^[|\s:-]+$/.test(line)
}

/** 去掉包裹表格的代码围栏：GLM 常把表格套进 ``` 块输出，按代码渲染会显示原始 Markdown */
function unwrapFencedTables(src: string): string {
  return src.replace(/```[^\n]*\n([\s\S]*?)```/g, (fence, body: string) => {
    const lines = body.split('\n').filter((l) => l.trim())
    const [header, separator] = lines
    if (header && separator && header.includes('|') && isTableSeparator(separator)) {
      return body // 围栏内容是表格：拆掉围栏按表格渲染
    }
    return fence // 普通代码块原样保留
  })
}

/** 表格行的全角竖线「｜」归一化为半角（GFM 只认 |；仅处理以｜起头的行，避免误伤正文） */
function normalizeTablePipes(src: string): string {
  return src
    .split('\n')
    .map((l) => (l.trimStart().startsWith('｜') ? l.replaceAll('｜', '|') : l))
    .join('\n')
}

/** AI 回答按受控 Markdown 渲染，经 DOMPurify 消毒（技术栈.md #17：禁 v-html 直插原始回答） */
function renderAnswer(src: string): string {
  const md = normalizeTablePipes(unwrapFencedTables(src))
  return DOMPurify.sanitize(marked.parse(md, { async: false }))
}

/** 思考过程面板标题：流式且正文未开始时显示进行中，其余显示字数 */
function reasoningLabel(msg: ChatMessage): string {
  if (msg.streaming && !msg.content) return '深度思考中…'
  return `深度思考过程（${msg.reasoning?.length ?? 0} 字）`
}

function sourceMeta(kind: string, s: Record<string, unknown>): string {
  const bits: string[] = []
  if (kind === 'bid_subject') {
    if (s.award_amount_wan !== undefined) bits.push(`${s.award_amount_wan} 万元`)
    const time = (s.award_time ?? s.publish_time) as string | undefined
    if (time) bits.push(String(time).slice(0, 10))
  } else if (s.publish_time) {
    bits.push(String(s.publish_time).slice(0, 10))
  }
  return bits.join(' · ')
}

async function scrollBottom() {
  await nextTick()
  listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
}

function retryLast() {
  const lastUser = [...messages.value].reverse().find((m) => m.role === 'user')
  if (!lastUser) return
  if (lastUser.imageFile) {
    // 图片解析失败重试：原图还在消息上，复用上一次的回答气泡
    const answer = messages.value[messages.value.indexOf(lastUser) + 1]
    if (answer) {
      answer.content = ''
      answer.failed = false
      answer.streaming = true
      void runParse(lastUser.imageFile, answer)
    }
    return
  }
  void send(lastUser.content)
}

/** 复制回答原文（Markdown 源文本）；clipboard API 不可用时降级 execCommand */
async function copyAnswer(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    ElMessage.success('已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = content
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    if (ok) ElMessage.success('已复制')
    else ElMessage.error('复制失败，请手动选择文本')
  }
}

/** 重新生成：移除该问答对（及其后的消息）并重发同一个问题 */
function regenerate(index: number) {
  if (sending.value) return
  const user = messages.value[index - 1]
  if (!user || user.role !== 'user' || user.imageFile) return
  messages.value.splice(index - 1)
  void send(user.content)
}

/** 用时统计文案：同阶段/同工具合并（×N），如"意图分析 0.9s · 招投标知识库 1.2s ×2 · 共 6.8s" */
function timingText(msg: ChatMessage): string {
  if (!msg.timing?.length) return ''
  const order: string[] = []
  const agg = new Map<string, { label: string; seconds: number; count: number }>()
  for (const s of msg.timing) {
    const label =
      s.key === 'tool'
        ? (TOOL_LABELS[s.tool ?? ''] ?? s.tool ?? '工具')
        : (STAGE_LABELS[s.key] ?? s.key)
    const key = s.key === 'tool' ? `tool:${s.tool ?? ''}` : s.key
    const cur = agg.get(key)
    if (cur) {
      cur.seconds += s.seconds
      cur.count += 1
    } else {
      order.push(key)
      agg.set(key, { label, seconds: s.seconds, count: 1 })
    }
  }
  const parts = order.map((key) => {
    const { label, seconds, count } = agg.get(key)!
    return `${label} ${seconds.toFixed(1)}s${count > 1 ? ` ×${count}` : ''}`
  })
  if (msg.totalSeconds !== undefined) parts.push(`共 ${msg.totalSeconds.toFixed(1)}s`)
  return parts.join(' · ')
}

/** 点赞/点踩（再点一次撤销），乐观更新、失败回滚 */
async function rateAnswer(msg: ChatMessage, value: '赞' | '踩') {
  if (!msg.qaId) return
  const next = msg.rating === value ? '' : value
  const prev = msg.rating
  msg.rating = next || undefined
  try {
    await setQaEvaluation(msg.qaId, next)
  } catch (e) {
    msg.rating = prev
    ElMessage.error(errMsg(e, '反馈失败，请重试'))
  }
}

/** 选择附件图片：校验类型与大小后仅本地预览，随下一次发送一起提交 */
function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
    ElMessage.warning('仅支持 jpg/png/webp/gif 格式的图片')
    return
  }
  if (file.size > MAX_IMAGE_BYTES) {
    ElMessage.warning('图片不能超过 5MB')
    return
  }
  removePending()
  pendingImage.value = { file, url: URL.createObjectURL(file) }
}

function removePending() {
  if (pendingImage.value) URL.revokeObjectURL(pendingImage.value.url)
  pendingImage.value = null
}

async function send(text?: string) {
  const question = (text ?? input.value).trim()
  if (sending.value) return
  if (pendingImage.value) {
    void sendImage()
    return
  }
  if (!question) {
    ElMessage.warning(TEXTS.emptyQuestion)
    return
  }
  input.value = ''
  sending.value = true
  activeTool.value = ''
  trackSendClick() // FR-08 埋点：'发送'按钮/页面点击/次数（失败静默）
  messages.value.push({ role: 'user', content: question })
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  const answer = messages.value[messages.value.length - 1] as ChatMessage
  scrollBottom()

  try {
    await streamChat(question, (ev) => {
      switch (ev.type) {
        case 'reasoning':
          // 深度思考过程：流式展开，正文开始时自动收起（用户仍可手动展开）
          if (!answer.reasoning) {
            answer.reasoning = ''
            answer.reasoningOpen = true
          }
          answer.reasoning += ev.text
          activeTool.value = ''
          scrollBottom()
          break
        case 'delta':
          activeTool.value = ''
          if (!answer.content && answer.reasoning) answer.reasoningOpen = false
          answer.content += ev.text
          scrollBottom()
          break
        case 'sources':
          answer.sources = ev.items
          break
        case 'chart':
          // spec 非法时静默忽略，不影响文字回答
          if (isValidChartSpec(ev.spec)) answer.chart = ev.spec
          break
        case 'clarify':
          // 主动澄清：渲染成带快捷选项的气泡，点击选项即作为下一问发送
          answer.clarify = {
            question: ev.question,
            options: Array.isArray(ev.options) ? ev.options.filter((o) => o.trim()) : [],
          }
          activeTool.value = ''
          scrollBottom()
          break
        case 'timing':
          answer.timing = ev.stages
          answer.totalSeconds = ev.total
          break
        case 'meta':
          answer.qaId = ev.qa_id
          break
        case 'status':
          if (ev.stage === 'tool_call' && ev.tool) {
            activeTool.value = `正在查询：${TOOL_LABELS[ev.tool] ?? ev.tool}`
          } else if (ev.stage === 'analysis' && ev.text) {
            // ReAct 每轮分析：截断成一行展示在加载提示区
            const t = ev.text
            activeTool.value = `💭 ${t.length > 60 ? `${t.slice(0, 60)}…` : t}`
          } else if (ev.stage === 'quality') {
            // 结果质量不达标：空结果/相关性偏低/调用失败
            const v = ev.verdict === 'empty' ? '结果为空' : ev.verdict === 'weak' ? '相关性偏低' : '查询异常'
            const t = ev.text ?? ''
            activeTool.value = `⚠️ ${v}，调整策略：${t.length > 46 ? `${t.slice(0, 46)}…` : t}`
          } else if (ev.stage === 'generating') {
            // 深度思考时首个思考 token 到来前显示提示（reasoning 事件会清空它）
            activeTool.value = deepThinking.value ? '深度思考中…' : ''
          }
          break
        case 'error':
          answer.failed = true
          ElMessage.error(ev.message || TEXTS.genFailed)
          break
      }
    }, {
      webSearch: webSearch.value,
      sessionId: getSessionId(),
      model: selectedModel.value || undefined,
      deepThinking: deepThinking.value,
    })
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) {
      answer.failed = true
      ElMessage.error(errMsg(e, TEXTS.genFailed))
    }
  } finally {
    answer.streaming = false
    activeTool.value = ''
    sending.value = false
    void refreshSearch() // 流式渲染会冲掉高亮标记，落定后重建
    scrollBottom()
  }
}
async function sendImage() {
  const img = pendingImage.value
  if (!img || sending.value) return
  // 只清空引用：预览 URL 随消息缩略图继续使用，不能 revoke
  pendingImage.value = null
  messages.value.push({
    role: 'user',
    content: input.value.trim(),
    image: img.url,
    imageFile: img.file,
  })
  input.value = ''
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  const answer = messages.value[messages.value.length - 1] as ChatMessage
  await runParse(img.file, answer)
}

async function runParse(file: File, answer: ChatMessage) {
  sending.value = true
  activeTool.value = TEXTS.parsingImage
  scrollBottom()
  try {
    const { content } = await parseImage(file)
    if (!content) throw new Error(TEXTS.parseFailed)
    answer.content = content
  } catch (e) {
    answer.failed = true
    ElMessage.error(errMsg(e, TEXTS.parseFailed))
  } finally {
    answer.streaming = false
    activeTool.value = ''
    sending.value = false
    void refreshSearch()
    scrollBottom()
  }
}

/** Enter 发送 / Shift+Enter 换行；IME 组合中不触发（中文输入） */
function onKeydown(e: Event | KeyboardEvent) {
  if (!(e instanceof KeyboardEvent)) return
  if (e.key !== 'Enter') return
  if (e.shiftKey || e.isComposing) return
  e.preventDefault()
  void send()
}

function logout() {
  auth.logout()
  router.push('/login')
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKey)
  window.clearTimeout(searchTimer)
})
</script>

<template>
  <div class="chat-page">
    <header class="app-header">
      <div class="brand">
        <BrandLogo :size="30" />
        <span class="name">Kael Mind</span>
        <span class="brand-sep">·</span>
        <span class="brand-sub">{{ TEXTS.appTitle }}</span>
      </div>
      <div class="user-zone">
        <el-button link type="primary" @click="newChat">
          <el-icon><Plus /></el-icon>
          <span>新对话</span>
        </el-button>
        <el-button link type="primary" @click="toggleSearch()">
          <el-icon><Search /></el-icon>
          <span>搜索</span>
        </el-button>
        <el-button link type="primary" @click="openHistory">
          <el-icon><Clock /></el-icon>
          <span>历史对话</span>
        </el-button>
        <el-button v-if="auth.isAdmin" link type="primary" @click="router.push('/admin/qa-list')">
          维护后台
        </el-button>
        <el-tag size="small" type="info" effect="plain">{{ auth.user?.user_type }}</el-tag>
        <span class="username">{{ auth.user?.display_name }}</span>
        <el-button link @click="logout">退出</el-button>
      </div>
    </header>

    <!-- 对话内容搜索条（Ctrl+F 式：高亮全部命中 + 上下跳转） -->
    <div v-if="searchOpen" class="search-bar">
      <el-input
        ref="searchInputRef"
        v-model="searchKeyword"
        class="search-input"
        placeholder="搜索当前对话内容"
        clearable
        @input="onSearchInput"
        @keydown="onSearchKeydown"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <span class="search-count" :class="{ none: !!searchKeyword.trim() && !searchHits.length }">
        {{ searchCountText }}
      </span>
      <button type="button" class="icon-btn" aria-label="上一个命中" :disabled="!searchHits.length" @click="stepSearch(-1)">
        <el-icon><ArrowUp /></el-icon>
      </button>
      <button type="button" class="icon-btn" aria-label="下一个命中" :disabled="!searchHits.length" @click="stepSearch(1)">
        <el-icon><ArrowDown /></el-icon>
      </button>
      <button type="button" class="icon-btn" aria-label="关闭搜索" @click="toggleSearch(false)">
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <main ref="listRef" class="conversation" role="log" aria-live="polite" aria-label="对话消息">
      <div v-if="messages.length === 0" class="empty-state">
        <div class="welcome">{{ TEXTS.welcome }}</div>
        <div class="examples">
          <el-tag
            v-for="q in EXAMPLES"
            :key="q"
            class="example-tag"
            effect="plain"
            @click="send(q)"
          >
            {{ q }}
          </el-tag>
        </div>
      </div>

      <template v-for="(msg, i) in messages" :key="i">
        <div v-if="msg.role === 'user'" class="row user-row">
          <div class="bubble user-bubble">
            <img v-if="msg.image" class="user-image" :src="msg.image" alt="用户上传的图片" />
            <span v-if="msg.content">{{ msg.content }}</span>
          </div>
        </div>
        <div v-else class="row answer-row">
          <div class="answer-card">
            <!-- 深度思考过程（可折叠；正文开始后自动收起） -->
            <div v-if="msg.reasoning" class="reasoning">
              <button
                type="button"
                class="reasoning-head"
                :aria-expanded="!!msg.reasoningOpen"
                @click="msg.reasoningOpen = !msg.reasoningOpen"
              >
                <el-icon v-if="msg.streaming && !msg.content" class="is-loading"><Loading /></el-icon>
                <svg
                  v-else
                  viewBox="0 0 24 24"
                  width="14"
                  height="14"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.7.6 1 1.4 1 2.3h6c0-.9.3-1.7 1-2.3A7 7 0 0 0 12 2z" />
                </svg>
                <span>{{ reasoningLabel(msg) }}</span>
                <el-icon class="reasoning-arrow" :class="{ open: msg.reasoningOpen }"><ArrowDown /></el-icon>
              </button>
              <div v-show="msg.reasoningOpen" class="reasoning-body">{{ msg.reasoning }}</div>
            </div>
            <template v-if="msg.content">
              <!-- 回答已消毒后渲染 -->
              <div class="answer-md" v-html="renderAnswer(msg.content)" />
            </template>
            <template v-else-if="!msg.reasoning && !msg.clarify">
              <div v-if="activeTool" class="tool-hint">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>{{ activeTool }}</span>
              </div>
              <div v-else class="typing" aria-label="回答生成中">
                <span /><span /><span />
              </div>
            </template>

            <!-- 主动澄清：问题 + 可点击的快捷选项（点击即作为下一问发送） -->
            <div v-if="msg.clarify" class="clarify">
              <div class="clarify-title">需要向您确认</div>
              <div class="clarify-question">{{ msg.clarify.question }}</div>
              <div v-if="msg.clarify.options.length" class="clarify-options">
                <button
                  v-for="(option, oi) in msg.clarify.options"
                  :key="oi"
                  type="button"
                  class="clarify-option"
                  :disabled="sending"
                  @click="send(option)"
                >
                  {{ option }}
                </button>
              </div>
            </div>

            <!-- 图表回答：chart 事件在回答下方渲染，与来源芯片同属回答卡片 -->
            <ChartBlock
              v-if="msg.chart && (msg.content || !msg.streaming)"
              :spec="msg.chart"
            />

            <div v-if="msg.sources?.length" class="sources">
              <div class="sources-title">参考来源（{{ msg.sources.length }}）</div>
              <div v-for="(s, si) in msg.sources" :key="si" class="source-item">
                <el-tag size="small" effect="plain" class="source-kind">{{ SOURCE_LABELS[s.kind] ?? s.kind }}</el-tag>
                <a v-if="s.url" class="source-title source-link" :href="s.url" target="_blank" rel="noopener">
                  {{ s.title }}
                </a>
                <span v-else class="source-title">{{ s.title }}</span>
                <span v-if="s.url && s.score !== undefined" class="source-score">
                  相关性 {{ Math.round(s.score * 100) }}%
                </span>
                <span v-if="sourceMeta(s.kind, s)" class="source-meta">{{ sourceMeta(s.kind, s) }}</span>
              </div>
            </div>

            <!-- 各阶段用时（timing 事件；历史恢复的旧消息无此数据） -->
            <div v-if="!msg.streaming && timingText(msg)" class="timing-line">
              <el-icon><Clock /></el-icon>
              <span>{{ timingText(msg) }}</span>
            </div>

            <!-- 操作行：仅对已完成的文本回答展示（图片解析回答无问答记录，走失败重试流） -->
            <div v-if="!msg.streaming && msg.content && !messages[i - 1]?.imageFile" class="answer-actions">
              <el-tooltip content="复制" placement="top">
                <button type="button" class="action-btn" aria-label="复制回答" @click="copyAnswer(msg.content)">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <rect x="9" y="9" width="13" height="13" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                </button>
              </el-tooltip>
              <el-tooltip content="重新生成" placement="top">
                <button type="button" class="action-btn" aria-label="重新生成回答" @click="regenerate(i)">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <polyline points="23 4 23 10 17 10" />
                    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                  </svg>
                </button>
              </el-tooltip>
              <template v-if="msg.qaId">
                <el-tooltip content="有帮助" placement="top">
                  <button
                    type="button"
                    class="action-btn"
                    :class="{ active: msg.rating === '赞' }"
                    :aria-pressed="msg.rating === '赞'"
                    aria-label="反馈：有帮助"
                    @click="rateAnswer(msg, '赞')"
                  >
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" />
                    </svg>
                  </button>
                </el-tooltip>
                <el-tooltip content="没帮助" placement="top">
                  <button
                    type="button"
                    class="action-btn"
                    :class="{ active: msg.rating === '踩' }"
                    :aria-pressed="msg.rating === '踩'"
                    aria-label="反馈：没帮助"
                    @click="rateAnswer(msg, '踩')"
                  >
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17" />
                    </svg>
                  </button>
                </el-tooltip>
              </template>
            </div>
            <div v-if="msg.failed" class="failed-zone">
              <span class="failed-text">{{ TEXTS.genFailed }}</span>
              <el-button size="small" type="primary" link @click="retryLast">重试</el-button>
            </div>
          </div>
        </div>
      </template>
    </main>

    <footer class="composer">
      <div class="composer-box">
        <div v-if="pendingImage" class="pending-image">
          <img :src="pendingImage.url" alt="待发送图片" />
          <el-button class="remove-btn" link aria-label="移除图片" @click="removePending">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
        <input
          ref="fileRef"
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          hidden
          @change="onFileChange"
        />
        <el-input
          v-model="input"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          resize="none"
          placeholder="请输入问题或输入指令获取收藏指令，可通过 Shift+回车换行"
          :disabled="sending"
          @keydown="onKeydown"
        />
        <div class="composer-toolbar">
          <div class="toolbar-left">
            <el-tooltip :content="TEXTS.attachImage" placement="top">
              <button
                type="button"
                class="icon-btn"
                :disabled="sending"
                :aria-label="TEXTS.attachImage"
                @click="fileRef?.click()"
              >
                <el-icon :size="17"><Paperclip /></el-icon>
              </button>
            </el-tooltip>
            <el-tooltip :content="currentModelTip" placement="top">
              <el-dropdown
                trigger="click"
                popper-class="model-popper"
                :disabled="sending"
                @command="onModelCommand"
              >
                <button
                  type="button"
                  class="web-chip"
                  :class="{ active: !!selectedModel }"
                  :disabled="sending"
                  :aria-label="currentModelTip"
                >
                  <el-icon :size="14"><Cpu /></el-icon>
                  <span class="model-chip-label">{{ currentModelLabel }}</span>
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="!modelItems.length" disabled>
                      模型清单加载中…
                    </el-dropdown-item>
                    <el-dropdown-item
                      v-for="m in modelItems"
                      :key="m.id"
                      :command="m.id"
                      :disabled="m.available === false"
                    >
                      <div class="model-item">
                        <div class="model-head">
                          <span class="model-id">{{ m.id }}</span>
                          <el-tag size="small" effect="plain" :type="m.is_default ? 'primary' : 'info'">
                            {{ m.label }}
                          </el-tag>
                          <span v-if="m.id === selectedModel" class="model-check">✓</span>
                          <span v-if="m.available === false" class="model-reason">{{ m.reason }}</span>
                        </div>
                        <div v-if="m.hint" class="model-hint">{{ m.hint }}</div>
                      </div>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </el-tooltip>
            <button
              type="button"
              class="web-chip"
              :class="{ active: webSearch }"
              :disabled="sending"
              :aria-pressed="webSearch"
              @click="toggleWebSearch"
            >
              <svg
                viewBox="0 0 24 24"
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="9" />
                <path d="M3 12h18" />
                <path d="M12 3c2.5 2.6 3.8 5.7 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.7-3.8-9S9.5 5.6 12 3z" />
              </svg>
              <span>联网搜索</span>
            </button>
            <el-tooltip
              content="深度思考：最终作答使用更强推理，首字延迟增加（工具检索轮次不变）"
              placement="top"
            >
              <button
                type="button"
                class="web-chip"
                :class="{ active: deepThinking }"
                :disabled="sending"
                :aria-pressed="deepThinking"
                aria-label="深度思考"
                @click="toggleDeepThinking"
              >
                <svg
                  viewBox="0 0 24 24"
                  width="14"
                  height="14"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.7.6 1 1.4 1 2.3h6c0-.9.3-1.7 1-2.3A7 7 0 0 0 12 2z" />
                </svg>
                <span>深度思考</span>
              </button>
            </el-tooltip>
          </div>
          <el-button
            type="primary"
            class="send-btn"
            circle
            :disabled="sending || (!input.trim() && !pendingImage)"
            :aria-label="sending ? '生成中' : '发送'"
            @click="send()"
          >
            <el-icon v-if="sending" class="is-loading"><Loading /></el-icon>
            <el-icon v-else><ArrowUp /></el-icon>
          </el-button>
        </div>
      </div>
    </footer>

    <el-drawer v-model="historyOpen" title="历史对话" size="360px">
      <div class="history-search">
        <el-input
          v-model="historyKeyword"
          placeholder="搜索问题或回答关键词"
          clearable
          @keyup.enter="searchHistory"
          @clear="searchHistory"
        >
          <template #append>
            <el-button :icon="Search" aria-label="搜索历史对话" @click="searchHistory" />
          </template>
        </el-input>
      </div>
      <div v-if="historyLoading" class="history-empty">加载中…</div>
      <template v-else>
        <div v-if="!historySessions.length" class="history-empty">暂无历史对话</div>
        <div v-for="s in historySessions" :key="s.session_id" class="history-item">
          <div class="history-main" @click="restoreSession(s)">
            <span class="history-title">{{ s.title }}</span>
            <span class="history-meta">{{ s.count }} 条问答 · {{ s.last_time.slice(0, 16) }}</span>
          </div>
          <el-dropdown trigger="click" popper-class="history-popper" @command="() => removeSession(s)">
            <button type="button" class="history-more-btn" :aria-label="`更多操作：${s.title}`">
              <el-icon><MoreFilled /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="delete">删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <el-button
          v-if="historySessions.length < historyTotal"
          class="history-more"
          link
          type="primary"
          @click="loadMoreHistory"
        >
          加载更多（{{ historyTotal - historySessions.length }}）
        </el-button>
      </template>
      <div v-if="!historyLoading && historyTotal > 0" class="history-footer">
        <el-button link type="danger" aria-label="清空全部对话" @click="removeAllSessions">
          清空全部对话（{{ historyTotal }} 组）
        </el-button>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.chat-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.app-header {
  height: var(--app-header-height);
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 16px;
}

.brand-sep,
.brand-sub {
  font-weight: 400;
  font-size: 13px;
  color: #909399;
}

@media (max-width: 720px) {
  .brand-sep,
  .brand-sub {
    display: none;
  }
}

.user-zone {
  display: flex;
  align-items: center;
  gap: 10px;
}

.username {
  color: #606266;
}

.conversation {
  flex: 1;
  overflow-y: auto;
  padding: 24px 0;
}

/* ── 对话内容搜索 ── */
.search-bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 20px;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
}

.search-input {
  width: min(420px, 60vw);
}

.search-count {
  min-width: 56px;
  font-size: 12px;
  color: #909399;
  text-align: center;
}

.search-count.none {
  color: #f56c6c;
}

/* 命中标记由运行时注入（v-html 文本节点），scoped 需 :deep 穿透 */
.conversation :deep(mark.search-hit) {
  background: #ffe58f;
  color: #303133;
  border-radius: 2px;
  padding: 0 1px;
}

.conversation :deep(mark.search-hit.active) {
  background: #ff9f43;
  color: #fff;
}

.empty-state {
  text-align: center;
  margin-top: 15vh;
}

.welcome {
  font-size: 18px;
  color: #606266;
  margin-bottom: 20px;
}

.example-tag {
  cursor: pointer;
  margin: 0 6px;
  font-size: 13px;
}

.row {
  display: flex;
  padding: 8px 20px;
}

.user-row {
  justify-content: flex-end;
}

.user-bubble {
  max-width: 70%;
  background: var(--app-primary);
  color: #fff;
  border-radius: 10px 10px 2px 10px;
  padding: 10px 14px;
  white-space: pre-wrap;
  word-break: break-word;
}

.user-image {
  display: block;
  max-width: 200px;
  max-height: 150px;
  border-radius: 6px;
  margin-bottom: 4px;
}

.answer-row {
  justify-content: flex-start;
}

.answer-card {
  max-width: 78%;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 2px 10px 10px 10px;
  padding: 12px 16px;
}

/* 深度思考过程：标题行 + 可折叠正文（流式时展开，正文开始后自动收起） */
.reasoning {
  margin-bottom: 8px;
}

.reasoning-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 4px 2px;
  border: none;
  background: transparent;
  color: #909399;
  font-size: 12px;
  cursor: pointer;
  transition: color 0.2s;
}

.reasoning-head:hover {
  color: var(--app-primary);
}

.reasoning-arrow {
  margin-left: auto;
  transition: transform 0.2s;
}

.reasoning-arrow.open {
  transform: rotate(180deg);
}

.reasoning-body {
  max-height: 240px;
  overflow-y: auto;
  margin-top: 4px;
  padding: 8px 10px;
  border-left: 2px solid #dcdfe6;
  border-radius: 4px;
  background: #fafafa;
  color: #909399;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.answer-md :deep(p) {
  margin: 0 0 8px;
  line-height: 1.7;
}

/* Markdown 分节小标题（企业画像的「概况 / 经营状况 / 中标表现 / 风险提示」等） */
.answer-md :deep(h1),
.answer-md :deep(h2),
.answer-md :deep(h3),
.answer-md :deep(h4) {
  margin: 12px 0 6px;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--app-primary);
}

.answer-md :deep(h1:first-child),
.answer-md :deep(h2:first-child),
.answer-md :deep(h3:first-child),
.answer-md :deep(h4:first-child) {
  margin-top: 0;
}

.answer-md :deep(ol),
.answer-md :deep(ul) {
  padding-left: 20px;
  margin: 0 0 8px;
}

/* Markdown 表格：块级+横向滚动防撑破气泡 */
.answer-md :deep(table) {
  display: block;
  overflow-x: auto;
  border-collapse: collapse;
  margin: 8px 0;
  max-width: 100%;
  font-size: 13px;
}

.answer-md :deep(th),
.answer-md :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 6px 12px;
  text-align: left;
  line-height: 1.5;
  word-break: break-word;
}

.answer-md :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
  white-space: nowrap;
}

.answer-md :deep(tbody tr:nth-child(even) td) {
  background: #fafcff;
}

/* 代码块与行内代码 */
.answer-md :deep(pre) {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  font-size: 12px;
  margin: 0 0 8px;
}

.answer-md :deep(code) {
  font-family: Consolas, Monaco, 'Courier New', monospace;
}

.answer-md :deep(:not(pre) > code) {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12px;
}

.tool-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #909399;
  font-size: 13px;
}

.typing {
  display: inline-flex;
  gap: 4px;
  padding: 4px 0;
}

.typing span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #c0c4cc;
  animation: blink 1.2s infinite ease-in-out;
}

.typing span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%,
  80%,
  100% {
    opacity: 0.3;
  }
  40% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .typing span {
    animation: none;
  }
}

/* 主动澄清气泡：与普通回答区分，选项点击后作为下一问发送 */
.clarify {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid #d9ecff;
  border-radius: 8px;
  background: #f4f9ff;
}

.clarify-title {
  color: var(--app-primary);
  font-size: 12px;
  font-weight: 600;
}

.clarify-question {
  color: #303133;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.clarify-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.clarify-option {
  padding: 6px 12px;
  border: 1px solid #b3d8ff;
  border-radius: 16px;
  background: #fff;
  color: var(--app-primary);
  font-size: 13px;
  line-height: 1.4;
  text-align: left;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
}

.clarify-option:hover:not(:disabled) {
  border-color: var(--app-primary);
  background: var(--app-primary);
  color: #fff;
}

.clarify-option:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.answer-chart {
  width: 100%;
  height: 300px;
  margin-top: 10px;
}

.sources {
  margin-top: 10px;
  border-top: 1px dashed #e4e7ed;
  padding-top: 8px;
}

.sources-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.source-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  line-height: 1.8;
}

.source-kind {
  flex: none;
}

.source-title {
  color: #606266;
  word-break: break-all;
}

.source-link {
  color: var(--app-primary);
  text-decoration: none;
}

.source-link:hover {
  text-decoration: underline;
}

.source-score {
  flex: none;
  font-size: 12px;
  color: #67c23a;
  background: #f0f9eb;
  border-radius: 8px;
  padding: 0 6px;
}

.source-meta {
  flex: none;
  color: #c0c4cc;
}

.failed-zone {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.failed-text {
  color: #f56c6c;
  font-size: 13px;
}

/* 各阶段用时（timing 事件）：意图分析 · 工具执行 · 生成回答 · 总用时 */
.timing-line {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
}

.timing-line .el-icon {
  font-size: 13px;
}

/* 回答操作行：复制 / 重新生成 / 点赞点踩 */
.answer-actions {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 2px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #c0c4cc;
  cursor: pointer;
  transition: color 0.2s, background 0.2s;
}

.action-btn:hover,
.action-btn.active {
  background: #f2f6fc;
  color: var(--app-primary);
}

.composer {
  flex: none;
  padding: 10px 20px 16px;
}

/* OpenAI 风格浮岛输入框：文本区在上、工具行（附件/联网/发送）在下 */
.composer-box {
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 24px;
  padding: 6px 10px 8px 14px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.composer-box:focus-within {
  border-color: var(--app-primary);
  box-shadow: 0 2px 14px rgba(64, 158, 255, 0.14);
}

/* 文本区去掉自带边框，融入外层圆角容器 */
.composer-box :deep(.el-textarea__inner) {
  box-shadow: none;
  background: transparent;
  padding: 6px 4px;
  line-height: 1.6;
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 2px 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: #606266;
  cursor: pointer;
}

.icon-btn:hover:not(:disabled) {
  background: #f2f6fc;
  color: var(--app-primary);
}

.icon-btn:disabled {
  color: #c0c4cc;
  cursor: not-allowed;
}

.web-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 12px;
  border: 1px solid #dcdfe6;
  border-radius: 999px;
  background: #fff;
  color: #606266;
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s, color 0.2s;
}

.web-chip:hover:not(:disabled),
.web-chip.active {
  border-color: var(--app-primary);
  color: var(--app-primary);
}

.web-chip.active {
  background: #ecf5ff;
}

.web-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.model-chip-label {
  max-width: 130px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 模型下拉挂在 body 下，需全局作用域（scoped 内 :global） */
:global(.model-popper .model-item) {
  min-width: 240px;
  line-height: 1.4;
}

:global(.model-popper .model-head) {
  display: flex;
  align-items: center;
  gap: 6px;
}

:global(.model-popper .model-id) {
  font-weight: 600;
  font-size: 13px;
  color: #303133;
}

:global(.model-popper .model-check) {
  font-size: 12px;
  color: var(--app-primary);
}

:global(.model-popper .model-reason) {
  font-size: 12px;
  color: #f56c6c;
}

:global(.model-popper .model-hint) {
  margin-top: 2px;
  font-size: 12px;
  color: #909399;
}

.pending-image {
  position: relative;
  align-self: flex-start;
  margin: 4px 4px 8px;
  padding: 4px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #f5f7fa;
}

.pending-image img {
  display: block;
  max-width: 160px;
  max-height: 100px;
  border-radius: 4px;
}

.remove-btn {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 20px;
  height: 20px;
  padding: 0;
  border-radius: 50%;
  background: #909399;
  color: #fff;
}

.remove-btn:hover {
  background: #f56c6c;
  color: #fff;
}

.send-btn {
  width: 32px;
  height: 32px;
  flex: none;
}

/* ── 历史对话抽屉 ── */
.history-search {
  margin-bottom: 12px;
}

.history-empty {
  padding: 32px 0;
  text-align: center;
  color: #909399;
  font-size: 13px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  margin-bottom: 8px;
  padding: 4px 6px 4px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fff;
  transition: border-color 0.2s, background 0.2s;
}

.history-item:hover {
  border-color: var(--app-primary);
  background: #f0f7ff;
}

.history-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 0;
  cursor: pointer;
  text-align: left;
}

.history-more-btn {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #909399;
  cursor: pointer;
}

.history-more-btn:hover {
  background: #f2f6fc;
  color: var(--app-primary);
}

/* 下拉菜单挂在 body 下，需全局作用域（scoped 内 :global） */
:global(.history-popper .el-dropdown-menu__item) {
  color: #f56c6c;
}

.history-title {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 13px;
  color: #303133;
  line-height: 1.5;
}

.history-meta {
  font-size: 12px;
  color: #909399;
}

.history-more {
  width: 100%;
  margin-top: 4px;
}

.history-footer {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #e4e7ed;
  text-align: center;
}
</style>
