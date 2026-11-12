import type { SseEvent } from '@/types'
import { TOKEN_KEY } from './http'

export interface StreamChatOptions {
  signal?: AbortSignal
  /** 联网搜索开关：开启后 Agent 必查本地知识库+联网搜索 */
  webSearch?: boolean
  /** 会话 ID（前端生成、localStorage 持久化），对话历史按会话聚合 */
  sessionId?: string
  /** 回答文本问题所用模型 id；空 = 跟随后端默认 */
  model?: string
  /** 深度思考开关：最终作答调高思考强度（DeepSeek 下切 reasoner 模型） */
  deepThinking?: boolean
}

/**
 * POST SSE：EventSource 仅支持 GET，故用 fetch + ReadableStream 解析 data 帧。
 * 断流/异常以 reject 抛出，由调用方渲染错误态与重试。
 */
export async function streamChat(
  question: string,
  onEvent: (e: SseEvent) => void,
  options: StreamChatOptions = {},
): Promise<void> {
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY) ?? ''}`,
    },
    body: JSON.stringify({
      question,
      web_search: options.webSearch ?? false,
      session_id: options.sessionId ?? null,
      model: options.model ?? null,
      deep_thinking: options.deepThinking ?? false,
    }),
    signal: options.signal,
  })
  if (resp.status === 401) {
    localStorage.removeItem(TOKEN_KEY)
    location.href = '/login'
    throw new Error('登录已过期，请重新登录')
  }
  if (!resp.ok) {
    // 后端校验失败（如模型不在候选清单）时 detail 是用户可读的，优先透出
    let detail = ''
    try {
      detail = (await resp.json()).detail ?? ''
    } catch {
      /* 非 JSON 响应体，忽略 */
    }
    throw new Error(detail || `请求失败(${resp.status})`)
  }
  if (!resp.body) throw new Error(`请求失败(${resp.status})`)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data: ')) continue
        onEvent(JSON.parse(line.slice(6)) as SseEvent)
      }
    }
  }
}
