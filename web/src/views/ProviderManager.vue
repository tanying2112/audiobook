<script setup lang="ts">
import { onMounted, ref, reactive } from 'vue'
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
    alert(t('provider_manager.loading') + ' ' + (e?.message || e))
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
    alert(t('provider_manager.loading') + ' ' + (e?.message || e))
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
    alert(t('provider_manager.name') + ' ' + t('common.required'))
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
    await loadProviders()
  } catch (e: any) {
    alert(t('provider_manager.save_failed') + (e?.message || e))
  } finally {
    providerDialog.saving = false
  }
}

async function removeProvider(p: ProviderOut) {
  if (!confirm(t('provider_manager.delete_confirm').replace('{name}', p.name))) return
  try {
    await deleteProvider(p.id)
    if (selectedProvider.value?.id === p.id) {
      selectedProvider.value = null
      models.value = []
    }
    await loadProviders()
  } catch (e: any) {
    alert(t('provider_manager.delete_failed') + (e?.message || e))
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
    alert(t('provider_manager.model_name') + ' ' + t('common.required'))
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
    await loadModels(pid)
  } catch (e: any) {
    alert(t('provider_manager.save_failed') + (e?.message || e))
  } finally {
    modelDialog.saving = false
  }
}

async function removeModel(m: ModelOut) {
  if (!selectedProvider.value) return
  if (!confirm(t('provider_manager.model_delete_confirm').replace('{name}', m.name))) return
  try {
    await deleteModel(selectedProvider.value.id, m.id)
    await loadModels(selectedProvider.value.id)
  } catch (e: any) {
    alert(t('provider_manager.delete_failed') + (e?.message || e))
  }
}

// ── Hot reload ───────────────────────────────────────────────────────────
async function onReload() {
  try {
    const res = await reloadProviders()
    if (res.errors && res.errors.length) {
      alert(t('provider_manager.reload_failed') + res.errors.join('; '))
    } else {
      alert(t('provider_manager.reload_success'))
    }
  } catch (e: any) {
    alert(t('provider_manager.reload_failed') + (e?.message || e))
  }
}

onMounted(loadProviders)
</script>

<template>
  <div class="provider-manager">
    <div class="breadcrumb">
      <span>首页</span>
      <span class="sep">/</span>
      <span>供应商管理</span>
    </div>

    <div class="page-header">
      <div>
        <h1>{{ t('provider_manager.title') }}</h1>
        <p class="subtitle">{{ t('provider_manager.subtitle') }}</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-primary" @click="openCreateProvider">
          {{ t('provider_manager.add_provider') }}
        </button>
        <button class="btn" @click="onReload" :title="t('provider_manager.reload_help')">
          {{ t('provider_manager.reload') }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">{{ t('provider_manager.loading') }}</div>

    <div v-else class="layout">
      <!-- Provider table -->
      <div class="card">
        <div class="card-title">{{ t('provider_manager.provider_list') }} ({{ providers.length }})</div>
        <table class="data-table" v-if="providers.length">
          <thead>
            <tr>
              <th>{{ t('provider_manager.name') }}</th>
              <th>{{ t('provider_manager.display_name') }}</th>
              <th>{{ t('provider_manager.provider_type') }}</th>
              <th>{{ t('provider_manager.status_enabled') }}</th>
              <th>{{ t('provider_manager.sort_priority') }}</th>
              <th>{{ t('provider_manager.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="p in providers"
              :key="p.id"
              :class="{ selected: selectedProvider && selectedProvider.id === p.id }"
              @click="selectProvider(p)"
            >
              <td>{{ p.name }}</td>
              <td>{{ p.display_name || '-' }}</td>
              <td>{{ p.provider_type }}</td>
              <td>
                <span :class="['tag', p.is_enabled ? 'tag-ok' : 'tag-bad']">
                  {{ p.is_enabled ? t('provider_manager.status_enabled') : t('provider_manager.status_disabled') }}
                </span>
              </td>
              <td>{{ p.sort_priority }}</td>
              <td>
                <button class="btn btn-sm" @click.stop="openEditProvider(p)">
                  {{ t('provider_manager.edit_provider') }}
                </button>
                <button class="btn btn-sm btn-danger" @click.stop="removeProvider(p)">
                  {{ t('common.delete') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">{{ t('provider_manager.no_providers') }}</div>
      </div>

      <!-- Model table -->
      <div class="card" v-if="selectedProvider">
        <div class="card-title">
          {{ t('provider_manager.model_list') }} ({{ models.length }})
          <button class="btn btn-sm btn-primary" @click="openCreateModel">
            {{ t('provider_manager.add_model') }}
          </button>
        </div>
        <table class="data-table" v-if="models.length">
          <thead>
            <tr>
              <th>{{ t('provider_manager.model_name') }}</th>
              <th>{{ t('provider_manager.model_id') }}</th>
              <th>{{ t('provider_manager.version') }}</th>
              <th>{{ t('provider_manager.context_window') }}</th>
              <th>{{ t('provider_manager.status_enabled') }}</th>
              <th>{{ t('provider_manager.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in models" :key="m.id">
              <td>{{ m.name }}</td>
              <td>{{ m.model_id || '-' }}</td>
              <td>{{ m.version || '-' }}</td>
              <td>{{ m.context_window }}</td>
              <td>
                <span :class="['tag', m.is_enabled ? 'tag-ok' : 'tag-bad']">
                  {{ m.is_enabled ? t('provider_manager.status_enabled') : t('provider_manager.status_disabled') }}
                </span>
              </td>
              <td>
                <button class="btn btn-sm" @click="openEditModel(m)">
                  {{ t('provider_manager.edit_model') }}
                </button>
                <button class="btn btn-sm btn-danger" @click="removeModel(m)">
                  {{ t('common.delete') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">{{ t('provider_manager.select_provider_hint') }}</div>
      </div>
    </div>

    <!-- Provider dialog -->
    <div v-if="providerDialog.visible" class="modal-overlay" @click.self="providerDialog.visible = false">
      <div class="modal">
        <h2>{{ providerDialog.editing ? t('provider_manager.edit_provider') : t('provider_manager.add_provider') }}</h2>
        <div class="form-grid">
          <label>{{ t('provider_manager.name') }} *</label>
          <input v-model="providerDialog.form.name" type="text" class="form-control" />

          <label>{{ t('provider_manager.display_name') }}</label>
          <input v-model="providerDialog.form.display_name" type="text" class="form-control" />

          <label>{{ t('provider_manager.provider_type') }}</label>
          <select v-model="providerDialog.form.provider_type" class="form-control">
            <option v-for="t2 in PROVIDER_TYPES" :key="t2" :value="t2">{{ t2 }}</option>
          </select>

          <label>{{ t('provider_manager.api_base') }}</label>
          <input v-model="providerDialog.form.api_base" type="text" class="form-control" placeholder="https://api.openai.com/v1" />

          <label>{{ t('provider_manager.api_key') }}</label>
          <input v-model="providerDialog.form.api_key" type="password" class="form-control" />

          <label>{{ t('provider_manager.auth_type') }}</label>
          <select v-model="providerDialog.form.auth_type" class="form-control">
            <option v-for="a in AUTH_TYPES" :key="a" :value="a">{{ a }}</option>
          </select>

          <label>{{ t('provider_manager.default_model') }}</label>
          <input v-model="providerDialog.form.default_model" type="text" class="form-control" />

          <label>{{ t('provider_manager.max_tokens') }}</label>
          <input v-model.number="providerDialog.form.max_tokens" type="number" class="form-control" />

          <label>{{ t('provider_manager.temperature') }}</label>
          <input v-model.number="providerDialog.form.temperature" type="number" step="0.01" class="form-control" />

          <label>{{ t('provider_manager.sort_priority') }}</label>
          <input v-model.number="providerDialog.form.sort_priority" type="number" class="form-control" />

          <label>{{ t('provider_manager.is_enabled') }}</label>
          <input v-model="providerDialog.form.is_enabled" type="checkbox" class="form-check" />
        </div>
        <div class="modal-actions">
          <button class="btn btn-primary" :disabled="providerDialog.saving" @click="saveProvider">
            {{ t('provider_manager.save') }}
          </button>
          <button class="btn btn-ghost" @click="providerDialog.visible = false">
            {{ t('provider_manager.cancel') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Model dialog -->
    <div v-if="modelDialog.visible" class="modal-overlay" @click.self="modelDialog.visible = false">
      <div class="modal">
        <h2>{{ modelDialog.editing ? t('provider_manager.edit_model') : t('provider_manager.add_model') }}</h2>
        <div class="form-grid">
          <label>{{ t('provider_manager.model_name') }} *</label>
          <input v-model="modelDialog.form.name" type="text" class="form-control" />

          <label>{{ t('provider_manager.model_id') }}</label>
          <input v-model="modelDialog.form.model_id" type="text" class="form-control" placeholder="gpt-4o" />

          <label>{{ t('provider_manager.version') }}</label>
          <input v-model="modelDialog.form.version" type="text" class="form-control" />

          <label>{{ t('provider_manager.context_window') }}</label>
          <input v-model.number="modelDialog.form.context_window" type="number" class="form-control" />

          <label>{{ t('provider_manager.sort_priority') }}</label>
          <input v-model.number="modelDialog.form.sort_priority" type="number" class="form-control" />

          <label>{{ t('provider_manager.is_enabled') }}</label>
          <input v-model="modelDialog.form.is_enabled" type="checkbox" class="form-check" />
        </div>
        <div class="modal-actions">
          <button class="btn btn-primary" :disabled="modelDialog.saving" @click="saveModel">
            {{ t('provider_manager.save') }}
          </button>
          <button class="btn btn-ghost" @click="modelDialog.visible = false">
            {{ t('provider_manager.cancel') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.provider-manager { max-width: 1100px; margin: 0 auto; padding: 20px; }
.breadcrumb { margin-bottom: 16px; color: #94a3b8; font-size: 13px; }
.breadcrumb .sep { margin: 0 6px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 20px; gap: 16px; flex-wrap: wrap; }
.page-header h1 { margin: 0 0 4px; font-size: 22px; }
.subtitle { margin: 0; color: #64748b; font-size: 13px; }
.header-actions { display: flex; gap: 8px; }
.layout { display: flex; flex-direction: column; gap: 16px; }
.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; }
.card-title { font-weight: 600; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
.data-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.data-table th, .data-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #f1f5f9; }
.data-table tbody tr { cursor: pointer; }
.data-table tbody tr:hover { background: #f8fafc; }
.data-table tbody tr.selected { background: #eff6ff; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; }
.tag-ok { background: #dcfce7; color: #16a34a; }
.tag-bad { background: #fee2e2; color: #dc2626; }
.empty { text-align: center; padding: 24px; color: #94a3b8; }
.loading { text-align: center; padding: 60px; color: #64748b; }
.btn { padding: 8px 14px; border: 1px solid #cbd5e1; background: #fff; border-radius: 8px; cursor: pointer; font-size: 14px; }
.btn:hover { background: #f1f5f9; }
.btn-primary { background: #2563eb; color: #fff; border-color: #2563eb; }
.btn-primary:hover { background: #1d4ed8; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-ghost { background: transparent; border-color: transparent; color: #64748b; }
.btn-sm { padding: 5px 10px; font-size: 13px; margin-right: 4px; }
.btn-danger { background: #fee2e2; color: #dc2626; border-color: #fecaca; }
.btn-danger:hover { background: #fecaca; }
.modal-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; padding: 24px; border-radius: 12px; width: 100%; max-width: 520px; max-height: 90vh; overflow-y: auto; }
.modal h2 { margin: 0 0 18px; font-size: 18px; }
.form-grid { display: grid; grid-template-columns: 140px 1fr; gap: 12px 12px; align-items: center; }
.form-grid label { font-size: 13px; font-weight: 500; color: #334155; }
.form-control { padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; width: 100%; box-sizing: border-box; }
.form-check { width: 18px; height: 18px; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }
</style>
