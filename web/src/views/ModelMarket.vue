<script setup lang="ts">
import { onMounted, ref } from 'vue'
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
    error.value = e?.message || '加载模型市场失败'
  } finally {
    loading.value = false
  }
}

async function install(p: PluginEntry) {
  busy.value = p.name
  try {
    await installModel(p.name)
    await load()
  } catch (e: any) {
    error.value = e?.message || '安装失败'
  } finally {
    busy.value = null
  }
}

async function uninstall(p: PluginEntry) {
  busy.value = p.name
  try {
    await uninstallModel(p.name)
    await load()
  } catch (e: any) {
    error.value = e?.message || '卸载失败'
  } finally {
    busy.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="model-market">
    <h1>{{ t('nav.model_market') }}</h1>
    <p class="hint">免费资源模型市场:TTS 音色与可安装插件(注册式,无网络下载)。</p>

    <div v-if="loading">加载中…</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else-if="catalog">
      <section>
        <h2>TTS 引擎</h2>
        <div v-for="engine in catalog.tts_engines" :key="engine.engine" class="card">
          <h3>{{ engine.engine }} <span v-if="engine.free" class="badge">免费</span></h3>
          <ul>
            <li v-for="v in engine.voices" :key="v.model_id">
              {{ v.language }} · {{ v.voice }} <code>{{ v.model_id }}</code>
            </li>
          </ul>
        </div>
      </section>

      <section>
        <h2>插件</h2>
        <div v-for="p in catalog.plugins" :key="p.name" class="card">
          <h3>
            {{ p.name }} <span class="version">v{{ p.version }}</span>
            <span v-if="p.installed" class="badge installed">已安装</span>
          </h3>
          <p>{{ p.description }}</p>
          <p class="models">提供模型: {{ p.models.join(', ') }}</p>
          <button v-if="!p.installed" :disabled="busy === p.name" @click="install(p)">
            {{ busy === p.name ? '安装中…' : '一键安装' }}
          </button>
          <button v-else :disabled="busy === p.name" @click="uninstall(p)">卸载</button>
        </div>
      </section>

      <p class="total">共 {{ catalog.total_models }} 个可用模型</p>
    </template>
  </div>
</template>

<style scoped>
.model-market { padding: 24px; }
.hint { color: #888; }
.card { border: 1px solid #ddd; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; }
.badge { background: #2e7d32; color: #fff; border-radius: 4px; padding: 2px 6px; font-size: 12px; }
.badge.installed { background: #1565c0; }
.version { color: #888; font-size: 13px; }
.models { color: #666; font-size: 13px; }
.error { color: #c62828; }
.total { margin-top: 16px; color: #555; }
</style>
