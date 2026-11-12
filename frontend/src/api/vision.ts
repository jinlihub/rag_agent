import { http } from './http'

export interface ParseImageResult {
  model: string
  content: string
}

/** 上传图片 → /api/vision/parse，视觉模型解析为 Markdown。解析耗时数秒，放宽超时 */
export async function parseImage(file: File): Promise<ParseImageResult> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<ParseImageResult>('/vision/parse', form, { timeout: 60_000 })
  return resp.data
}
