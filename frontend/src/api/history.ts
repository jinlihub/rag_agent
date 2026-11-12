import { http } from './http'
import type { HistoryMessage, HistorySession } from '@/types'

export interface HistorySessionsResult {
  total: number
  page: number
  page_size: number
  items: HistorySession[]
}

/** 当前用户的会话列表（新→旧；keyword 命中问题或回答即命中会话） */
export function fetchHistorySessions(
  params: { keyword?: string; page?: number; page_size?: number } = {},
): Promise<HistorySessionsResult> {
  return http.get<HistorySessionsResult>('/history/sessions', { params }).then((r) => r.data)
}

/** 按会话取全部消息（跨会话恢复） */
export function fetchSessionMessages(sessionId: string): Promise<{
  session_id: string
  messages: HistoryMessage[]
}> {
  return http
    .get<{ session_id: string; messages: HistoryMessage[] }>(`/history/sessions/${sessionId}`)
    .then((r) => r.data)
}

/** 删除整组历史对话 */
export function deleteHistorySession(sessionId: string): Promise<{ deleted: number }> {
  return http.delete<{ deleted: number }>(`/history/sessions/${sessionId}`).then((r) => r.data)
}

/** 清空全部对话记录（不可恢复） */
export function deleteAllSessions(): Promise<{ deleted: number }> {
  return http.delete<{ deleted: number }>('/history/sessions').then((r) => r.data)
}

/** 回答反馈：点赞/点踩（PUT /api/history/qa/{id}/evaluation）；evaluation 空 = 撤销 */
export function setQaEvaluation(qaId: number, evaluation: '赞' | '踩' | ''): Promise<void> {
  return http.put(`/history/qa/${qaId}/evaluation`, { evaluation }).then(() => undefined)
}
