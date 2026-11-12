import { http } from './http'
import type { AuthResponse } from '@/types'

export interface LoginPayload {
  username: string
  password: string
}

export interface RegisterPayload extends LoginPayload {
  email?: string
  user_type: string
  display_name?: string
}

export function login(payload: LoginPayload) {
  return http.post<AuthResponse>('/auth/login', payload)
}

export function register(payload: RegisterPayload) {
  return http.post<AuthResponse>('/auth/register', payload)
}
