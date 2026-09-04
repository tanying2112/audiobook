<script setup lang="ts">
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
</script>

<template>
  <div class="provider-manager">
    <div class="breadcrumb">
      <span>{{ t('common.home') }}</span>
      <span class="sep">/</span>
      <span>{{ t('nav.provider_management') }}</span>
    </div>

    <div class="page-header">
      <div>
        <h1>{{ t('provider_manager.title') }}</h1>
        <p class="subtitle">{{ t('provider_manager.subtitle') }}</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openCreateProvider">
          {{ t('provider_manager.add_provider') }}
        </el-button>
        <el-button @click="onReload" :title="t('provider_manager.reload_help')">
          {{ t('provider_manager.reload') }}
        </el-button>
      </div>
    </div>

    <div v-if="loading" class="loading">{{ t('provider_manager.loading') }}</div>

    <div v-else class="layout">
      <!-- Provider table -->
      <div class="card">
        <div class="card-title">{{ t('provider_manager.provider_list') }} ({{ providers.length }})</div>
        <el-table
          v-if="providers.length"
          :data="providers"
          highlight-current-row
          @current-change="(row: ProviderOut | null) => row && selectProvider(row)"
        >
          <el-table-column prop="name" :label="t('provider_manager.name')" min-width="120" />
          <el-table-column prop="display_name" :label="t('provider_manager.display_name')" min-width="120">
            <template #default="{ row }">{{ row.display_name || '-' }}</template>
          </el-table-column>
          <el-table-column prop="provider_type" :label="t('provider_manager.provider_type')" min-width="140" />
          <el-table-column :label="t('provider_manager.status_enabled')" width="110">
            <template #default="{ row }">
              <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">
                {{ row.is_enabled ? t('provider_manager.status_enabled') : t('provider_manager.status_disabled') }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="sort_priority" :label="t('provider_manager.sort_priority')" width="110" />
          <el-table-column :label="t('provider_manager.actions')" width="160">
            <template #default="{ row }">
              <el-button size="small" @click="openEditProvider(row)">
                {{ t('provider_manager.edit_provider') }}
              </el-button>
              <el-button size="small" type="danger" plain @click="removeProvider(row)">
                {{ t('common.delete') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="empty">{{ t('provider_manager.no_providers') }}</div>
      </div>

      <!-- Model table -->
      <div class="card" v-if="selectedProvider">
        <div class="card-title">
          {{ t('provider_manager.model_list') }} ({{ models.length }})
          <el-button size="small" type="primary" @click="openCreateModel">
            {{ t('provider_manager.add_model') }}
          </el-button>
        </div>
        <el-table v-if="models.length" :data="models" v-loading="modelLoading">
          <el-table-column prop="name" :label="t('provider_manager.model_name')" min-width="120" />
          <el-table-column prop="model_id" :label="t('provider_manager.model_id')" min-width="120">
            <template #default="{ row }">{{ row.model_id || '-' }}</template>
          </el-table-column>
          <el-table-column prop="version" :label="t('provider_manager.version')" min-width="100">
            <template #default="{ row }">{{ row.version || '-' }}</template>
          </el-table-column>
          <el-table-column prop="context_window" :label="t('provider_manager.context_window')" width="140" />
          <el-table-column :label="t('provider_manager.status_enabled')" width="110">
            <template #default="{ row }">
              <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">
                {{ row.is_enabled ? t('provider_manager.status_enabled') : t('provider_manager.status_disabled') }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('provider_manager.actions')" width="160">
            <template #default="{ row }">
              <el-button size="small" @click="openEditModel(row)">
                {{ t('provider_manager.edit_model') }}
              </el-button>
              <el-button size="small" type="danger" plain @click="removeModel(row)">
                {{ t('common.delete') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="empty">{{ t('provider_manager.select_provider_hint') }}</div>
      </div>
    </div>

    <!-- Provider dialog -->
    <el-dialog
      v-model="providerDialog.visible"
      :title="providerDialog.editing ? t('provider_manager.edit_provider') : t('provider_manager.add_provider')"
      width="560px"
    >
      <el-form label-position="top">
        <el-form-item :label="t('provider_manager.name') + ' *'">
          <el-input v-model="providerDialog.form.name" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.display_name')">
          <el-input v-model="providerDialog.form.display_name" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.provider_type')">
          <el-select v-model="providerDialog.form.provider_type" style="width: 100%">
            <el-option v-for="t2 in PROVIDER_TYPES" :key="t2" :label="t2" :value="t2" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('provider_manager.api_base')">
          <el-input v-model="providerDialog.form.api_base" placeholder="https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.api_key')">
          <el-input v-model="providerDialog.form.api_key" type="password" show-password />
        </el-form-item>
        <el-form-item :label="t('provider_manager.auth_type')">
          <el-select v-model="providerDialog.form.auth_type" style="width: 100%">
            <el-option v-for="a in AUTH_TYPES" :key="a" :label="a" :value="a" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('provider_manager.default_model')">
          <el-input v-model="providerDialog.form.default_model" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.max_tokens')">
          <el-input-number v-model="providerDialog.form.max_tokens" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.temperature')">
          <el-input-number v-model="providerDialog.form.temperature" :min="0" :max="2" :step="0.01" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.sort_priority')">
          <el-input-number v-model="providerDialog.form.sort_priority" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.is_enabled')">
          <el-switch v-model="providerDialog.form.is_enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="providerDialog.visible = false">{{ t('provider_manager.cancel') }}</el-button>
        <el-button type="primary" :loading="providerDialog.saving" @click="saveProvider">
          {{ t('provider_manager.save') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Model dialog -->
    <el-dialog
      v-model="modelDialog.visible"
      :title="modelDialog.editing ? t('provider_manager.edit_model') : t('provider_manager.add_model')"
      width="520px"
    >
      <el-form label-position="top">
        <el-form-item :label="t('provider_manager.model_name') + ' *'">
          <el-input v-model="modelDialog.form.name" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.model_id')">
          <el-input v-model="modelDialog.form.model_id" placeholder="gpt-4o" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.version')">
          <el-input v-model="modelDialog.form.version" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.context_window')">
          <el-input-number v-model="modelDialog.form.context_window" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.sort_priority')">
          <el-input-number v-model="modelDialog.form.sort_priority" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('provider_manager.is_enabled')">
          <el-switch v-model="modelDialog.form.is_enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialog.visible = false">{{ t('provider_manager.cancel') }}</el-button>
        <el-button type="primary" :loading="modelDialog.saving" @click="saveModel">
          {{ t('provider_manager.save') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.provider-manager { max-width: 1100px; margin: 0 auto; }
.breadcrumb { margin-bottom: 16px; color: var(--color-text-muted); font-size: 13px; }
.breadcrumb .sep { margin: 0 6px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 20px; gap: 16px; flex-wrap: wrap; }
.page-header h1 { margin: 0 0 4px; font-size: 22px; color: var(--color-text); }
.subtitle { margin: 0; color: var(--color-text-secondary); font-size: 13px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.layout { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--color-card-bg); border: 1px solid var(--color-border); border-radius: 10px; padding: 16px; }
.card-title { font-weight: 600; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; color: var(--color-text); }
.empty { text-align: center; padding: 24px; color: var(--color-text-muted); }
.loading { text-align: center; padding: 60px; color: var(--color-text-secondary); }
</style>