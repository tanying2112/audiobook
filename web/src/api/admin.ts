/** Admin API — 用户/角色/权限 + 系统配置（/api/auth/*, /config/*） */
import api from './index'

export interface AdminUser {
  id: number
  username: string
  email?: string
  is_active?: boolean
  is_superuser?: boolean
  roles?: string[]
  [key: string]: unknown
}

export interface AdminRole {
  name: string
  description?: string
  permissions?: string[]
  [key: string]: unknown
}

export async function fetchUsers(): Promise<AdminUser[]> {
  const { data } = await api.get('/api/auth/users')
  return data
}

export async function updateUser(userId: number, payload: Partial<AdminUser>): Promise<AdminUser> {
  const { data } = await api.put(`/api/auth/users/${userId}`, payload)
  return data
}

export async function deleteUser(userId: number): Promise<void> {
  await api.delete(`/api/auth/users/${userId}`)
}

export async function fetchRoles(): Promise<AdminRole[]> {
  const { data } = await api.get('/api/auth/roles')
  return data
}

export async function assignRole(userId: number, roleName: string): Promise<void> {
  await api.post(`/api/auth/users/${userId}/roles/${roleName}`)
}

export async function revokeRole(userId: number, roleName: string): Promise<void> {
  await api.delete(`/api/auth/users/${userId}/roles/${roleName}`)
}

export async function reloadAllConfig(): Promise<unknown> {
  const { data } = await api.post('/api/config/reload-all')
  return data
}

export async function fetchConfigStatus(): Promise<Record<string, unknown>> {
  const { data } = await api.get('/api/config/status')
  return data
}
