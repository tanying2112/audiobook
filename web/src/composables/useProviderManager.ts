import { onMounted, ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from '../i18n'
import {
  getProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  getModelsByProvider,
  createModel,
  updateModel,
  deleteModel,
  reloadProviders,
  type ProviderOut,
  type ModelOut,
} from '../api/provider_router'

export function useProviderManager() {
  const { t } = useI18n()

  // ── State ────────────────────────────────────────────────────────────────
  const providers = ref<ProviderOut[]>([])
  const selectedProvider = ref<ProviderOut | null>(null)
  const models = ref<ModelOut[]>([])
  const loading = ref(false)
  const modelLoading = ref(false)

  // ── Provider dialog ──────────────────────────────────────────────────────
  const providerDialog = reactive({
    visible: false,
    editing: false,
    saving: false,
    form: {
      id: 0,
      name: '',
      display_name: '',
      provider_type: 'openai',
      api_base: '',
      api_key: '',
      auth_type: 'bearer',
      default_model: '',
      max_tokens: 4000,
      temperature: 0.1,
      sort_priority: 100,
      is_enabled: true,
    } as Partial<ProviderOut> & { id: number },
  })

  // ── Model dialog ─────────────────────────────────────────────────────────
  const modelDialog = reactive({
    visible: false,
    editing: false,
    saving: false,
    form: {
      id: 0,
      name: '',
      model_id: '',
      version: '',
      context_window: 128000,
      is_enabled: true,
      sort_priority: 100,
    } as Partial<ModelOut> & { id: number },
  })

  const PROVIDER_TYPES = [
    'openai',
    'anthropic',
    'groq',
    'deepseek',
    'openrouter',
    'ollama',
    'gemini',
    'nvidia_nemotron',
    'fcc_gateway',
    'siliconcloud',
    'zhipu',
    'alibaba',
    'mistral',
    'volcengine',
    'tencent',
    'cohere',
    'together',
    'baidu_qianfan',
    'cloudflare',
    'github',
    'duck2api',
  ]

  const AUTH_TYPES = ['bearer', 'api_key', 'none']

  // ── Data loading ─────────────────────────────────────────────────────────
  async function loadProviders() {
    loading.value = true
    try {
      const res = await getProviders()
      providers.value = res.providers || []
      // Keep selection consistent if it still exists.
      if (selectedProvider.value) {
        const still = providers.value.find((p) => p.id === selectedProvider.value!.id)
        selectedProvider.value = still ?? null
        if (still) await loadModels(still.id)
      }
    } catch (e: any) {
      ElMessage.error(t('provider_manager.loading') + ' ' + (e?.message || e))
    } finally {
      loading.value = false
    }
  }

  async function loadModels(providerId: number) {
    modelLoading.value = true
    try {
      const res = await getModelsByProvider(providerId)
      models.value = res.models || []
    } catch (e: any) {
      ElMessage.error(t('provider_manager.loading') + ' ' + (e?.message || e))
    } finally {
      modelLoading.value = false
    }
  }

  function selectProvider(p: ProviderOut) {
    selectedProvider.value = p
    loadModels(p.id)
  }

  // ── Provider CRUD ────────────────────────────────────────────────────────
  function openCreateProvider() {
    providerDialog.editing = false
    providerDialog.form = {
      id: 0,
      name: '',
      display_name: '',
      provider_type: 'openai',
      api_base: '',
      api_key: '',
      auth_type: 'bearer',
      default_model: '',
      max_tokens: 4000,
      temperature: 0.1,
      sort_priority: 100,
      is_enabled: true,
    }
    providerDialog.visible = true
  }

  function openEditProvider(p: ProviderOut) {
    providerDialog.editing = true
    providerDialog.form = {
      id: p.id,
      name: p.name,
      display_name: p.display_name || '',
      provider_type: p.provider_type,
      api_base: p.api_base || '',
      api_key: p.api_key || '',
      auth_type: p.auth_type,
      default_model: p.default_model || '',
      max_tokens: p.max_tokens,
      temperature: p.temperature,
      sort_priority: p.sort_priority,
      is_enabled: p.is_enabled,
    }
    providerDialog.visible = true
  }

  async function saveProvider() {
    if (!providerDialog.form.name?.trim()) {
      ElMessage.warning(t('provider_manager.name') + ' ' + t('common.required'))
      return
    }
    providerDialog.saving = true
    try {
      const payload = {
        name: providerDialog.form.name.trim(),
        display_name: providerDialog.form.display_name || null,
        provider_type: providerDialog.form.provider_type,
        api_base: providerDialog.form.api_base || null,
        api_key: providerDialog.form.api_key || null,
        auth_type: providerDialog.form.auth_type,
        default_model: providerDialog.form.default_model || null,
        max_tokens: Number(providerDialog.form.max_tokens) || 4000,
        temperature: Number(providerDialog.form.temperature) ?? 0.1,
        sort_priority: Number(providerDialog.form.sort_priority) ?? 100,
        is_enabled: providerDialog.form.is_enabled,
      }
      if (providerDialog.editing) {
        await updateProvider(providerDialog.form.id, payload)
      } else {
        await createProvider(payload)
      }
      providerDialog.visible = false
      ElMessage.success(t('provider_manager.save_success'))
      await loadProviders()
    } catch (e: any) {
      ElMessage.error(t('provider_manager.save_failed') + (e?.message || e))
    } finally {
      providerDialog.saving = false
    }
  }

  async function removeProvider(p: ProviderOut) {
    try {
      await ElMessageBox.confirm(
        t('provider_manager.delete_confirm').replace('{name}', p.name),
        t('common.confirm'),
        { type: 'warning' }
      )
    } catch {
      return
    }
    try {
      await deleteProvider(p.id)
      if (selectedProvider.value?.id === p.id) {
        selectedProvider.value = null
        models.value = []
      }
      ElMessage.success(t('provider_manager.delete_success'))
      await loadProviders()
    } catch (e: any) {
      ElMessage.error(t('provider_manager.delete_failed') + (e?.message || e))
    }
  }

  // ── Model CRUD ───────────────────────────────────────────────────────────
  function openCreateModel() {
    if (!selectedProvider.value) return
    modelDialog.editing = false
    modelDialog.form = {
      id: 0,
      name: '',
      model_id: '',
      version: '',
      context_window: 128000,
      is_enabled: true,
      sort_priority: 100,
    }
    modelDialog.visible = true
  }

  function openEditModel(m: ModelOut) {
    modelDialog.editing = true
    modelDialog.form = {
      id: m.id,
      name: m.name,
      model_id: m.model_id || '',
      version: m.version || '',
      context_window: m.context_window,
      is_enabled: m.is_enabled,
      sort_priority: m.sort_priority,
    }
    modelDialog.visible = true
  }

  async function saveModel() {
    if (!selectedProvider.value) return
    if (!modelDialog.form.name?.trim()) {
      ElMessage.warning(t('provider_manager.model_name') + ' ' + t('common.required'))
      return
    }
    modelDialog.saving = true
    try {
      const pid = selectedProvider.value.id
      const payload = {
        name: modelDialog.form.name.trim(),
        model_id: modelDialog.form.model_id || null,
        version: modelDialog.form.version || null,
        context_window: Number(modelDialog.form.context_window) || 128000,
        is_enabled: modelDialog.form.is_enabled,
        sort_priority: Number(modelDialog.form.sort_priority) ?? 100,
      }
      if (modelDialog.editing) {
        await updateModel(pid, modelDialog.form.id, payload)
      } else {
        await createModel(pid, payload)
      }
      modelDialog.visible = false
      ElMessage.success(t('provider_manager.save_success'))
      await loadModels(pid)
    } catch (e: any) {
      ElMessage.error(t('provider_manager.save_failed') + (e?.message || e))
    } finally {
      modelDialog.saving = false
    }
  }

  async function removeModel(m: ModelOut) {
    if (!selectedProvider.value) return
    try {
      await ElMessageBox.confirm(
        t('provider_manager.model_delete_confirm').replace('{name}', m.name),
        t('common.confirm'),
        { type: 'warning' }
      )
    } catch {
      return
    }
    try {
      await deleteModel(selectedProvider.value.id, m.id)
      ElMessage.success(t('provider_manager.delete_success'))
      await loadModels(selectedProvider.value.id)
    } catch (e: any) {
      ElMessage.error(t('provider_manager.delete_failed') + (e?.message || e))
    }
  }

  // ── Hot reload ───────────────────────────────────────────────────────────
  async function onReload() {
    try {
      const res = await reloadProviders()
      if (res.errors && res.errors.length) {
        ElMessage.error(t('provider_manager.reload_failed') + res.errors.join('; '))
      } else {
        ElMessage.success(t('provider_manager.reload_success'))
      }
    } catch (e: any) {
      ElMessage.error(t('provider_manager.reload_failed') + (e?.message || e))
    }
  }

  onMounted(loadProviders)

  return {
    t,
    providers,
    selectedProvider,
    models,
    loading,
    modelLoading,
    providerDialog,
    modelDialog,
    PROVIDER_TYPES,
    AUTH_TYPES,
    selectProvider,
    openCreateProvider,
    openEditProvider,
    saveProvider,
    removeProvider,
    openCreateModel,
    openEditModel,
    saveModel,
    removeModel,
    onReload,
  }
}
