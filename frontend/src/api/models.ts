import { http } from './http'

/** 可选回答模型（GET /api/models） */
export interface ChatModel {
  id: string
  /** 短标签：默认 / 更强 / 轻量 … */
  label: string
  /** 下拉项副标题说明 */
  hint?: string
  is_default: boolean
  /** 可用性探测结果；null = 尚未探完（后端异步探测，稍后重取即可） */
  available: boolean | null
  /** available=false 时的原因文案 */
  reason?: string | null
}

export interface ModelsResult {
  default: string
  items: ChatModel[]
}

const MODELS_KEY = 'rag_llm_model'

export function fetchModels(): Promise<ModelsResult> {
  return http.get<ModelsResult>('/models').then((r) => r.data)
}

/** 用户选定的回答模型（空串 = 跟随后端默认） */
export function getSelectedModel(): string {
  return localStorage.getItem(MODELS_KEY) ?? ''
}

export function setSelectedModel(id: string): void {
  localStorage.setItem(MODELS_KEY, id)
}
