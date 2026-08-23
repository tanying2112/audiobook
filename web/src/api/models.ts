import api from './index'

export interface TtsVoice {
  model_id: string
  language: string
  voice: string
  engine: string
}

export interface TtsEngine {
  engine: string
  free: boolean
  voices: TtsVoice[]
}

export interface PluginEntry {
  name: string
  version: string
  type: string
  description: string
  models: string[]
  installed: boolean
}

export interface ModelCatalog {
  tts_engines: TtsEngine[]
  plugins: PluginEntry[]
  total_models: number
}

export async function listModels(): Promise<ModelCatalog> {
  const { data } = await api.get<ModelCatalog>('/models')
  return data
}

export async function installModel(name: string): Promise<{ name: string; installed: boolean; already_installed: boolean }> {
  const { data } = await api.post(`/models/install?name=${encodeURIComponent(name)}`)
  return data
}

export async function uninstallModel(name: string): Promise<{ name: string; removed: boolean }> {
  const { data } = await api.post(`/models/uninstall?name=${encodeURIComponent(name)}`)
  return data
}
