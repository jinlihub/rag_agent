import axios from 'axios'

import { TEXTS } from '@/constants/texts'

export const TOKEN_KEY = 'rag_token'

/** 直接读 localStorage，避免 http ↔ store 循环引用 */
export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem('rag_user')
}

export const http = axios.create({ baseURL: '/api', timeout: 15000 })

http.interceptors.request.use((cfg) => {
  const token = getToken()
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

http.interceptors.response.use(
  (resp) => resp,
  (err) => {
    const status: number | undefined = err.response?.status
    if (status === 401) {
      clearToken()
      if (!location.pathname.startsWith('/login')) location.href = '/login'
      err.message = '登录已过期，请重新登录'
    } else if (!err.response) {
      err.message = TEXTS.netError
    }
    return Promise.reject(err)
  },
)

/** 提取后端错误为可展示文案 */
export function errMsg(e: unknown, fallback: string = TEXTS.netError): string {
  if (axios.isAxiosError(e)) {
    const detail = e.response?.data?.detail
    return typeof detail === 'string' ? detail : e.message || fallback
  }
  return e instanceof Error ? e.message : fallback
}
