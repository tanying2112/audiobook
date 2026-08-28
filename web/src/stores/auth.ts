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
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const user = ref<User | null>(null)

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  function setRefreshToken(newRefreshToken: string) {
    refreshToken.value = newRefreshToken
    localStorage.setItem('refresh_token', newRefreshToken)
  }

  function setTokens(accessToken: string, newRefreshToken: string) {
    setToken(accessToken)
    setRefreshToken(newRefreshToken)
  }

  function setUser(userData: User) {
    user.value = userData
  }

  function clearAuth() {
    token.value = null
    refreshToken.value = null
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('refresh_token')
  }

  async function login(credentials: LoginRequest): Promise<TokenResponse> {
    const formData = new FormData()
    formData.append('username', credentials.username)
    formData.append('password', credentials.password)

    const { data } = await api.default.post<TokenResponse>('/api/auth/login', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })

    setTokens(data.access_token, data.refresh_token)
    return data
  }

  async function refreshAccessToken(): Promise<string | null> {
    if (!refreshToken.value) return null
    
    try {
      const { data } = await api.default.post<TokenResponse>('/api/auth/refresh', {
        refresh_token: refreshToken.value,
      })
      setTokens(data.access_token, data.refresh_token)
      return data.access_token
    } catch {
      clearAuth()
      return null
    }
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
    refreshToken,
    user,
    setToken,
    setRefreshToken,
    setTokens,
    clearAuth,
    login,
    refreshAccessToken,
    fetchUser,
    logout,
    isAuthenticated,
  }
})
