<script setup lang="ts">
import './ProviderManager.css'
import { useProviderManager } from '../composables/useProviderManager'
import type { ProviderOut } from '../api/provider_router'

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

