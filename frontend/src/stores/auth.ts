import { defineStore } from 'pinia'

import { clearToken, TOKEN_KEY } from '@/api/http'
import type { AuthResponse, User } from '@/types'

function loadUser(): User | null {
  try {
    return JSON.parse(localStorage.getItem('rag_user') ?? 'null') as User | null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) ?? '',
    user: loadUser(),
  }),
  getters: {
    isLoggedIn: (s) => Boolean(s.token),
    isAdmin: (s) => s.user?.role === 'admin',
  },
  actions: {
    setAuth(auth: AuthResponse) {
      this.token = auth.access_token
      this.user = auth.user
      localStorage.setItem(TOKEN_KEY, auth.access_token)
      localStorage.setItem('rag_user', JSON.stringify(auth.user))
    },
    logout() {
      this.token = ''
      this.user = null
      clearToken()
    },
  },
})
