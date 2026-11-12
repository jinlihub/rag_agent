import { TOKEN_KEY } from './http'

/** 浏览器会话 ID（localStorage 持久化；埋点与对话历史共用） */
export function getSessionId(): string {
  let sessionId = localStorage.getItem('rag_session')
  if (!sessionId) {
    sessionId = crypto.randomUUID()
    localStorage.setItem('rag_session', sessionId)
  }
  return sessionId
}

/** 开启新会话：轮换 ID，旧会话留在历史列表里 */
export function rotateSessionId(): void {
  localStorage.setItem('rag_session', crypto.randomUUID())
}

/**
 * 埋点直报（技术栈.md #7：请求层之外、交互层直报，失败静默不影响主流程）。
 * 事件名/属性名/属性值与 PRD §数据埋点字面一致（不进 i18n）。
 */
export function trackSendClick(page = '/chat'): void {
  fetch('/api/track', {
    method: 'POST',
    keepalive: true,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY) ?? ''}`,
    },
    body: JSON.stringify({
      event_name: '"发送"按钮',
      prop_name: '页面点击',
      prop_value: '次数',
      session_id: getSessionId(),
      page,
    }),
  }).catch(() => {})
}
