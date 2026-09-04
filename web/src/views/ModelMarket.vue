<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from '../i18n'
import { listModels, installModel, uninstallModel, type ModelCatalog, type PluginEntry } from '../api/models'

const { t } = useI18n()

const catalog = ref<ModelCatalog | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const busy = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    catalog.value = await listModels()
  } catch (e: any) {
    const msg = e?.message || t('model_market.load_failed')
    error.value = msg
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

async function install(p: PluginEntry) {
  busy.value = p.name
  try {
    await installModel(p.name)
    ElMessage.success(t('model_market.install_success'))
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || t('model_market.install_failed'))
  } finally {
    busy.value = null
  }
}

async function uninstall(p: PluginEntry) {
  busy.value = p.name
  try {
    await uninstallModel(p.name)
    ElMessage.success(t('model_market.uninstall_success'))
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || t('model_market.uninstall_failed'))
  } finally {
    busy.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="model-market">
    <div class="page-header">
      <div>
        <h1>{{ t('nav.model_market') }}</h1>
        <p class="hint">{{ t('model_market.hint') }}</p>
      </div>
    </div>

    <el-skeleton v-if="loading" :rows="5" animated />
    <el-alert v-else-if="error" :title="error" type="error" show-icon :closable="false" class="error-alert" />

    <template v-else-if="catalog">
      <section>
        <h2>{{ t('model_market.tts_engines') }}</h2>
        <el-card v-for="engine in catalog.tts_engines" :key="engine.engine" class="section-card" shadow="never">
          <template #header>
            <div class="card-header">
              <h3>
                {{ engine.engine }}
                <el-tag v-if="engine.free" type="success" size="small">{{ t('model_market.free') }}</el-tag>
              </h3>
            </div>
          </template>
          <el-table :data="engine.voices" size="small">
            <el-table-column prop="language" :label="t('model_market.language')" width="120" />
            <el-table-column prop="voice" :label="t('model_market.voice')" min-width="140" />
            <el-table-column prop="model_id" :label="t('model_market.model_id')" min-width="180">
              <template #default="{ row }"><code>{{ row.model_id }}</code></template>
            </el-table-column>
          </el-table>
        </el-card>
      </section>

      <section>
        <h2>{{ t('model_market.plugins') }}</h2>
        <el-card v-for="p in catalog.plugins" :key="p.name" class="section-card" shadow="never">
          <template #header>
            <div class="card-header">
              <h3>
                {{ p.name }}
                <span class="version">v{{ p.version }}</span>
                <el-tag v-if="p.installed" type="primary" size="small">{{ t('model_market.installed') }}</el-tag>
              </h3>
            </div>
          </template>
          <p>{{ p.description }}</p>
          <p class="models">{{ t('model_market.models_provided') }} {{ p.models.join(', ') }}</p>
          <el-button
            v-if="!p.installed"
            type="primary"
            :loading="busy === p.name"
            @click="install(p)"
          >
            {{ busy === p.name ? t('model_market.installing') : t('model_market.install') }}
          </el-button>
          <el-button v-else type="danger" plain :loading="busy === p.name" @click="uninstall(p)">
            {{ t('model_market.uninstall') }}
          </el-button>
        </el-card>
      </section>

      <p class="total">{{ t('model_market.total_models', { count: catalog.total_models }) }}</p>
    </template>
  </div>
</template>

<style scoped>
.model-market { padding: 24px; max-width: 1000px; margin: 0 auto; }
.page-header { margin-bottom: 20px; }
.page-header h1 { margin: 0 0 4px; font-size: 22px; color: var(--color-text); }
.hint { margin: 0; color: var(--color-text-secondary); font-size: 13px; }
h2 { font-size: 17px; margin: 24px 0 12px; color: var(--color-text); }
.section-card { margin-bottom: 12px; border: 1px solid var(--color-border); }
.card-header h3 { margin: 0; display: flex; align-items: center; gap: 8px; }
.version { color: var(--color-text-muted); font-size: 13px; font-weight: 400; }
.models { color: var(--color-text-secondary); font-size: 13px; }
.error-alert { margin-bottom: 16px; }
.total { margin-top: 20px; color: var(--color-text-secondary); }
</style>