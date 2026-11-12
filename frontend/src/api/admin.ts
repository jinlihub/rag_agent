import { http } from './http'
import type { QaClusterResult, QaListParams, QaListResult, SystemMetrics } from '@/types'

export function listQa(params: QaListParams) {
  return http.get<QaListResult>('/admin/qa', { params })
}

/** 编辑回答并保存 → 后端自动置为「已维护」 */
export function editAnswer(qaId: number, answer: string) {
  return http.put<{ id: number; maintain_status: string }>(`/admin/qa/${qaId}`, { answer })
}

export function markCorrect(qaId: number) {
  return http.post<{ id: number; maintain_status: string }>(`/admin/qa/${qaId}/mark-correct`)
}

export function noNeed(qaId: number) {
  return http.post<{ id: number; maintain_status: string }>(`/admin/qa/${qaId}/no-need`)
}

/** 未维护问题聚类视图（草稿由 scripts/cluster_unmaintained.py 离线生成，接口只读） */
export function listClusters() {
  return http.get<QaClusterResult>('/admin/clusters')
}

/** 一键确认：同簇全部未维护记录置为「已维护」 */
export function approveCluster(clusterId: number) {
  return http.post<{ id: number; updated: number; maintain_status: string }>(
    `/admin/clusters/${clusterId}/approve`,
  )
}

/** 系统监控快照（仅管理员）：CPU/内存/磁盘/GPU/进程/近期日志 */
export function getSystemMetrics(logLimit = 200) {
  return http.get<SystemMetrics>('/admin/system', { params: { log_limit: logLimit } })
}
