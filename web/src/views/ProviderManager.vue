<script setup lang="ts">
import { useProviderManager } from '../composables/useProviderManager'

const {
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
} = useProviderManager()
</script>

<template>
  <div class="page-container provider-manager">
    <div class="page-header">
      <div>
        <h1>{{ t('provider_manager.title') }}</h1>
        <p class="page-subtitle">{{ t('provider_manager.subtitle') }}</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-primary btn-sm" @click="openCreateProvider">
          {{ t('provider_manager.add_provider') }}
        </button>
        <button class="btn btn-outline btn-sm" @click="onReload" :aria-label="t('provider_manager.reload_help')">
          {{ t('provider_manager.reload') }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <span>{{ t('provider_manager.loading') }}</span>
    </div>

    <div v-else class="provider-layout">
      <!-- Provider table -->
      <div class="card">
        <div class="card-title">{{ t('provider_manager.provider_list') }} ({{ providers.length }})</div>
        <div class="table-responsive">
          <table class="table" v-if="providers.length">
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
                v-for="row in providers"
                :key="row.id"
                :class="{ 'row-selected': selectedProvider?.id === row.id }"
                @click="selectProvider(row)"
                role="button"
                tabindex="0"
                @keydown.enter="selectProvider(row)"
              >
                <td class="cell-name">{{ row.name }}</td>
                <td>{{ row.display_name || '—' }}</td>
                <td><span class="badge badge-muted">{{ row.provider_type }}</span></td>
                <td>
                  <span class="badge" :class="row.is_enabled ? 'badge-success' : 'badge-muted'">
                    {{ row.is_enabled ? t('provider_manager.status_enabled') : t('provider_manager.status_disabled') }}
                  </span>
                </td>
                <td>{{ row.sort_priority }}</td>
                <td class="cell-actions">
                  <button class="btn btn-sm btn-ghost" @click.stop="openEditProvider(row)" :aria-label="t('provider_manager.edit_provider')">
                    {{ t('provider_manager.edit_provider') }}
                  </button>
                  <button class="btn btn-sm btn-ghost btn-danger-text" @click.stop="removeProvider(row)" :aria-label="t('common.delete')">
                    {{ t('common.delete') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty-state">{{ t('provider_manager.no_providers') }}</div>
        </div>
      </div>

      <!-- Model table -->
      <div class="card" v-if="selectedProvider">
        <div class="card-title">
          <span>{{ t('provider_manager.model_list') }} ({{ models.length }})</span>
          <button class="btn btn-primary btn-sm" @click="openCreateModel">
            {{ t('provider_manager.add_model') }}
          </button>
        </div>
        <div class="table-responsive">
          <table class="table" v-if="models.length">
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
            <tbody v-loading="modelLoading">
              <tr v-for="row in models" :key="row.id">
                <td class="cell-name">{{ row.name }}</td>
                <td>{{ row.model_id || '—' }}</td>
                <td>{{ row.version || '—' }}</td>
                <td>{{ row.context_window }}</td>
                <td>
                  <span class="badge" :class="row.is_enabled ? 'badge-success' : 'badge-muted'">
                    {{ row.is_enabled ? t('provider_manager.status_enabled') : t('provider_manager.status_disabled') }}
                  </span>
                </td>
                <td class="cell-actions">
                  <button class="btn btn-sm btn-ghost" @click="openEditModel(row)" :aria-label="t('provider_manager.edit_model')">
                    {{ t('provider_manager.edit_model') }}
                  </button>
                  <button class="btn btn-sm btn-ghost btn-danger-text" @click="removeModel(row)" :aria-label="t('common.delete')">
                    {{ t('common.delete') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty-state">{{ t('provider_manager.select_provider_hint') }}</div>
        </div>
      </div>
    </div>

    <!-- Provider dialog -->
    <div v-if="providerDialog.visible" class="dialog-overlay" @click.self="providerDialog.visible = false">
      <div class="dialog" role="dialog" aria-modal="true" :aria-label="providerDialog.editing ? t('provider_manager.edit_provider') : t('provider_manager.add_provider')">
        <div class="dialog-header">
          <h2>{{ providerDialog.editing ? t('provider_manager.edit_provider') : t('provider_manager.add_provider') }}</h2>
          <button class="dialog-close" @click="providerDialog.visible = false" aria-label="Close">&times;</button>
        </div>
        <div class="dialog-body">
          <div class="form-group">
            <label>{{ t('provider_manager.name') }} *</label>
            <input v-model="providerDialog.form.name" class="form-control" />
          </div>
          <div class="form-group">
            <label>{{ t('provider_manager.display_name') }}</label>
            <input v-model="providerDialog.form.display_name" class="form-control" />
          </div>
          <div class="form-group">
            <label>{{ t('provider_manager.provider_type') }}</label>
            <select v-model="providerDialog.form.provider_type" class="form-control">
              <option v-for="t2 in PROVIDER_TYPES" :key="t2" :value="t2">{{ t2 }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>{{ t('provider_manager.api_base') }}</label>
            <input v-model="providerDialog.form.api_base" class="form-control" placeholder="https://api.openai.com/v1" />
          </div>
          <div class="form-group">
            <label>{{ t('provider_manager.api_key') }}</label>
            <input v-model="providerDialog.form.api_key" type="password" class="form-control" />
          </div>
          <div class="form-group">
            <label>{{ t('provider_manager.auth_type') }}</label>
            <select v-model="providerDialog.form.auth_type" class="form-control">
              <option v-for="a in AUTH_TYPES" :key="a" :value="a">{{ a }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>{{ t('provider_manager.default_model') }}</label>
            <input v-model="providerDialog.form.default_model" class="form-control" />
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>{{ t('provider_manager.max_tokens') }}</label>
              <input v-model.number="providerDialog.form.max_tokens" type="number" min="1" class="form-control" />
            </div>
            <div class="form-group">
              <label>{{ t('provider_manager.temperature') }}</label>
              <input v-model.number="providerDialog.form.temperature" type="number" min="0" max="2" step="0.01" class="form-control" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>{{ t('provider_manager.sort_priority') }}</label>
              <input v-model.number="providerDialog.form.sort_priority" type="number" class="form-control" />
            </div>
            <div class="form-group form-group-switch">
              <label>{{ t('provider_manager.is_enabled') }}</label>
              <label class="toggle" :class="{ on: providerDialog.form.is_enabled }" role="switch" :aria-checked="providerDialog.form.is_enabled" tabindex="0" @click="providerDialog.form.is_enabled = !providerDialog.form.is_enabled" @keydown.space.prevent="providerDialog.form.is_enabled = !providerDialog.form.is_enabled">
                <span class="toggle-knob"></span>
              </label>
            </div>
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn btn-outline btn-sm" @click="providerDialog.visible = false">{{ t('provider_manager.cancel') }}</button>
          <button class="btn btn-primary btn-sm" :disabled="providerDialog.saving" @click="saveProvider">
            <span v-if="providerDialog.saving" class="spinner"></span>
            {{ t('provider_manager.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Model dialog -->
    <div v-if="modelDialog.visible" class="dialog-overlay" @click.self="modelDialog.visible = false">
      <div class="dialog" role="dialog" aria-modal="true" :aria-label="modelDialog.editing ? t('provider_manager.edit_model') : t('provider_manager.add_model')">
        <div class="dialog-header">
          <h2>{{ modelDialog.editing ? t('provider_manager.edit_model') : t('provider_manager.add_model') }}</h2>
          <button class="dialog-close" @click="modelDialog.visible = false" aria-label="Close">&times;</button>
        </div>
        <div class="dialog-body">
          <div class="form-group">
            <label>{{ t('provider_manager.model_name') }} *</label>
            <input v-model="modelDialog.form.name" class="form-control" />
          </div>
          <div class="form-group">
            <label>{{ t('provider_manager.model_id') }}</label>
            <input v-model="modelDialog.form.model_id" class="form-control" placeholder="gpt-4o" />
          </div>
          <div class="form-group">
            <label>{{ t('provider_manager.version') }}</label>
            <input v-model="modelDialog.form.version" class="form-control" />
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>{{ t('provider_manager.context_window') }}</label>
              <input v-model.number="modelDialog.form.context_window" type="number" min="1" class="form-control" />
            </div>
            <div class="form-group">
              <label>{{ t('provider_manager.sort_priority') }}</label>
              <input v-model.number="modelDialog.form.sort_priority" type="number" class="form-control" />
            </div>
          </div>
          <div class="form-group form-group-switch">
            <label>{{ t('provider_manager.is_enabled') }}</label>
            <label class="toggle" :class="{ on: modelDialog.form.is_enabled }" role="switch" :aria-checked="modelDialog.form.is_enabled" tabindex="0" @click="modelDialog.form.is_enabled = !modelDialog.form.is_enabled" @keydown.space.prevent="modelDialog.form.is_enabled = !modelDialog.form.is_enabled">
              <span class="toggle-knob"></span>
            </label>
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn btn-outline btn-sm" @click="modelDialog.visible = false">{{ t('provider_manager.cancel') }}</button>
          <button class="btn btn-primary btn-sm" :disabled="modelDialog.saving" @click="saveModel">
            <span v-if="modelDialog.saving" class="spinner"></span>
            {{ t('provider_manager.save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.provider-layout { display: flex; flex-direction: column; gap: 16px; }

/* Table enhancements */
.row-selected { background: var(--color-primary-soft); }
.cell-name { font-weight: 500; }
.cell-actions { display: flex; gap: 4px; flex-wrap: wrap; }
.btn-danger-text { color: var(--color-danger); }
.btn-danger-text:hover { background: var(--color-danger-soft); }

/* Form row for side-by-side fields */
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

/* Toggle switch */
.form-group-switch { display: flex; flex-direction: column; gap: 6px; justify-content: flex-start; }
.toggle {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 24px;
  background: var(--color-border-strong);
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: background var(--transition-fast);
  flex-shrink: 0;
}
.toggle.on { background: var(--color-primary); }
.toggle-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 20px;
  height: 20px;
  background: #fff;
  border-radius: 50%;
  box-shadow: var(--shadow-xs);
  transition: transform var(--transition-fast);
}
.toggle.on .toggle-knob { transform: translateX(20px); }

/* Dialog */
.dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 16px; }
.dialog { background: var(--color-surface); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); width: 100%; max-width: 560px; max-height: calc(100vh - 32px); overflow-y: auto; }
.dialog-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--color-border); }
.dialog-header h2 { margin: 0; font-size: 17px; font-weight: 600; }
.dialog-close { background: none; border: none; font-size: 22px; color: var(--color-text-muted); cursor: pointer; padding: 0 4px; line-height: 1; }
.dialog-close:hover { color: var(--color-text); }
.dialog-body { padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.dialog-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 20px; border-top: 1px solid var(--color-border); }

@media (max-width: 767px) {
  .page-header { flex-direction: column; align-items: stretch; }
  .header-actions { justify-content: flex-end; }
  .form-row { grid-template-columns: 1fr; }
  .dialog { margin: 0; border-radius: var(--radius); }
  .cell-actions { flex-direction: column; }
}
</style>
