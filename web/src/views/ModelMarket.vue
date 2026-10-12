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
  <div class="page-container model-market">
    <div class="page-header">
      <div>
        <h1>{{ t('nav.model_market') }}</h1>
        <p class="page-subtitle">{{ t('model_market.hint') }}</p>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="alert alert-error error-alert">
      {{ error }}
    </div>

    <template v-else-if="catalog">
      <!-- TTS Engines -->
      <section class="market-section">
        <h2>{{ t('model_market.tts_engines') }}</h2>
        <div class="engine-list">
          <div v-for="engine in catalog.tts_engines" :key="engine.engine" class="card engine-card">
            <div class="engine-header">
              <h3 class="card-title">
                {{ engine.engine }}
                <span v-if="engine.free" class="badge badge-success">{{ t('model_market.free') }}</span>
              </h3>
            </div>
            <div class="table-responsive">
              <table class="table">
                <thead>
                  <tr>
                    <th>{{ t('model_market.language') }}</th>
                    <th>{{ t('model_market.voice') }}</th>
                    <th>{{ t('model_market.model_id') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(voice, i) in engine.voices" :key="i">
                    <td>{{ voice.language }}</td>
                    <td>{{ voice.voice }}</td>
                    <td><code class="mono">{{ voice.model_id }}</code></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <!-- Plugins -->
      <section class="market-section">
        <h2>{{ t('model_market.plugins') }}</h2>
        <div class="plugin-list">
          <div v-for="p in catalog.plugins" :key="p.name" class="card plugin-card">
            <div class="plugin-header">
              <div>
                <h3 class="card-title plugin-title">
                  {{ p.name }}
                  <span class="plugin-version">v{{ p.version }}</span>
                  <span v-if="p.installed" class="badge badge-info">{{ t('model_market.installed') }}</span>
                </h3>
              </div>
            </div>
            <p class="plugin-desc">{{ p.description }}</p>
            <p class="plugin-models">{{ t('model_market.models_provided') }} {{ p.models.join(', ') }}</p>
            <div class="plugin-actions">
              <button
                v-if="!p.installed"
                class="btn btn-primary btn-sm"
                :disabled="busy === p.name"
                @click="install(p)"
              >
                <span v-if="busy === p.name" class="spinner"></span>
                {{ busy === p.name ? t('model_market.installing') : t('model_market.install') }}
              </button>
              <button
                v-else
                class="btn btn-outline btn-sm btn-uninstall"
                :disabled="busy === p.name"
                @click="uninstall(p)"
              >
                <span v-if="busy === p.name" class="spinner"></span>
                {{ t('model_market.uninstall') }}
              </button>
            </div>
          </div>
        </div>
      </section>

      <p class="total-count">{{ t('model_market.total_models', { count: catalog.total_models }) }}</p>
    </template>
  </div>
</template>

<style scoped>
.market-section { margin-bottom: 24px; }
.market-section h2 {
  font-size: 17px;
  font-weight: 600;
  margin: 0 0 12px;
  color: var(--color-text);
}

/* Engine cards */
.engine-list { display: flex; flex-direction: column; gap: 12px; }
.engine-card { overflow: hidden; }
.engine-header { margin-bottom: 12px; }

/* Plugin cards */
.plugin-list { display: flex; flex-direction: column; gap: 12px; }
.plugin-card { overflow: hidden; }
.plugin-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.plugin-version {
  font-size: 13px;
  font-weight: 400;
  color: var(--color-text-muted);
  margin-left: 4px;
}
.plugin-desc {
  color: var(--color-text-secondary);
  font-size: 14px;
  margin: 0 0 6px;
}
.plugin-models {
  color: var(--color-text-secondary);
  font-size: 13px;
  margin: 0 0 12px;
}
.plugin-actions { display: flex; gap: 8px; }

.mono {
  font-family: var(--font-mono);
  font-size: 13px;
  background: var(--color-bg-tertiary);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}

.plugin-title { margin-bottom: 2px; }
.btn-uninstall { color: var(--color-danger); border-color: var(--color-danger); }
.btn-uninstall:hover { background: var(--color-danger-soft); }
.error-alert { margin-bottom: 16px; }
.total-count {
  margin-top: 20px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

@media (max-width: 767px) {
  .page-header { flex-direction: column; align-items: stretch; }
  .plugin-header { flex-direction: column; }
}
</style>
