import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api'

export interface User {
  id: number
  email: string
  username: string
  full_name?: string
  is_superuser: boolean
  is_active: boolean
}

export interface LoginRequest {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'))
  const user = ref<User | null>(null)

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  function setUser(userData: User) {
    user.value = userData
  }

  function clearAuth() {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
  }

  async function login(credentials: LoginRequest): Promise<TokenResponse> {
    const formData = new FormData()
    formData.append('username', credentials.username)
    formData.append('password', credentials.password)

    const { data } = await api.default.post<TokenResponse>('/api/auth/login', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })

    setToken(data.access_token)
    return data
  }

  async function fetchUser(): Promise<void> {
    if (!token.value) return
    try {
      const { data } = await api.default.get<User>('/api/auth/me')
      setUser(data)
    } catch {
      clearAuth()
    }
  }

  function logout() {
    clearAuth()
  }

  function isAuthenticated(): boolean {
    return !!token.value
  }

  return {
    token,
    user,
    setToken,
    setUser,
    clearAuth,
    login,
    fetchUser,
    logout,
    isAuthenticated,
  }
})