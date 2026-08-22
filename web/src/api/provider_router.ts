/**
 * 动态供应商管理 API 服务 (S2.1)
 *
 * 后端挂载路径（main.py）：/api/v1/providers
 * 复用 src/api/index.ts 导出的共享 axios 实例（自带鉴权拦截器）。
 */
import api from './index'

// ── 类型定义 ────────────────────────────────────────────────────────────────

export interface ProviderOut {
  id: number
  name: string
  display_name?: string | null
  description?: string | null
  provider_type: string
  api_base?: string | null
  api_key?: string | null
  auth_type: string
  default_model?: string | null
  max_tokens: number
  temperature: number
  is_enabled: boolean
  sort_priority: number
  created_by?: string | null
  model_count: number
}

export interface ProviderListResponse {
  providers: ProviderOut[]
  total: number
  page: number
  page_size: number
}

export interface ModelOut {
  id: number
  name: string
  provider_id: number
  model_id?: string | null
  version?: string | null
  context_window: number
  instructions?: Record<string, unknown> | null
  parameters?: Record<string, unknown> | null
  is_enabled: boolean
  sort_priority: number
  provider_name?: string | null
}

export interface ModelListResponse {
  models: ModelOut[]
  total: number
  provider_name?: string | null
}

export interface ReloadResponse {
  db_sync: string
  yaml_reload: string
  errors: string[]
}

// ── Provider CRUD ───────────────────────────────────────────────────────────

export async function getProviders(): Promise<ProviderListResponse> {
  const { data } = await api.get('/api/v1/providers/')
  return data
}

export async function getProvider(id: number): Promise<ProviderOut> {
  const { data } = await api.get(`/api/v1/providers/${id}`)
  return data
}

export async function createProvider(payload: Partial<ProviderOut>): Promise<ProviderOut> {
  const { data } = await api.post('/api/v1/providers/', payload)
  return data
}

export async function updateProvider(
  id: number,
  payload: Partial<ProviderOut>,
): Promise<ProviderOut> {
  const { data } = await api.put(`/api/v1/providers/${id}`, payload)
  return data
}

export async function deleteProvider(id: number): Promise<void> {
  await api.delete(`/api/v1/providers/${id}`)
}

// ── Model CRUD ──────────────────────────────────────────────────────────────

export async function getModelsByProvider(providerId: number): Promise<ModelListResponse> {
  const { data } = await api.get(`/api/v1/providers/${providerId}/models/`)
  return data
}

export async function createModel(
  providerId: number,
  payload: Partial<ModelOut>,
): Promise<ModelOut> {
  const { data } = await api.post(`/api/v1/providers/${providerId}/models/`, payload)
  return data
}

export async function updateModel(
  providerId: number,
  modelId: number,
  payload: Partial<ModelOut>,
): Promise<ModelOut> {
  const { data } = await api.put(
    `/api/v1/providers/${providerId}/models/${modelId}`,
    payload,
  )
  return data
}

export async function deleteModel(providerId: number, modelId: number): Promise<void> {
  await api.delete(`/api/v1/providers/${providerId}/models/${modelId}`)
}

// ── Hot reload ──────────────────────────────────────────────────────────────

export async function reloadProviders(): Promise<ReloadResponse> {
  const { data } = await api.post('/api/v1/providers/reload')
  return data
}

export default {
  getProviders,
  getProvider,
  createProvider,
  updateProvider,
  deleteProvider,
  getModelsByProvider,
  createModel,
  updateModel,
  deleteModel,
  reloadProviders,
}
