<template>
  <div class="sop-view">
    <div class="header">
      <h1>{{ t('sop.title') }}</h1>
      <div>
        <el-tag :type="bgStatus.running ? 'success' : 'info'" class="bg-tag">
          {{ t('sop.background') }}: {{ bgStatus.running ? t('common.on') : t('common.off') }}
        </el-tag>
        <el-button size="small" @click="toggleBackground">
          {{ bgStatus.running ? t('sop.stopBackground') : t('sop.startBackground') }}
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="6">
        <el-card>
          <template #header>{{ t('sop.genres') }}</template>
          <el-menu :default-active="activeGenre" @select="onSelectGenre">
            <el-menu-item v-for="g in genres" :key="g" :index="g">{{ g }}</el-menu-item>
          </el-menu>
          <el-empty v-if="genres.length === 0" :description="t('common.noData')" />
        </el-card>
      </el-col>
      <el-col :span="18">
        <el-card v-loading="loadingRules">
          <template #header>
            <div class="card-header">
              <span>{{ activeGenre || t('sop.selectGenre') }}</span>
              <el-button v-if="activeGenre" size="small" type="primary" :loading="reflecting" @click="onReflect">
                {{ t('sop.reflectNow') }}
              </el-button>
            </div>
          </template>
          <template v-if="rules">
            <div v-for="(val, key) in rules.rules" :key="key" class="rule-block">
              <h4>{{ key }}</h4>
              <pre>{{ JSON.stringify(val, null, 2) }}</pre>
            </div>
            <div v-if="Object.keys(rules.rules || {}).length === 0">
              <el-empty :description="t('sop.noRules')" />
            </div>
          </template>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from '../i18n'
import {
  fetchSopGenres,
  fetchSopGenreRules,
  triggerSopReflection,
  fetchSopBackgroundStatus,
  startSopBackground,
  stopSopBackground,
  type SopGenreRules,
} from '../api/sop'

const { t } = useI18n()
const genres = ref<string[]>([])
const activeGenre = ref('')
const rules = ref<SopGenreRules | null>(null)
const loadingRules = ref(false)
const reflecting = ref(false)
const bgStatus = ref<{ running?: boolean }>({})

async function load() {
  try {
    const [g, st] = await Promise.all([
      fetchSopGenres().catch(() => ({ genres: [] as string[] })),
      fetchSopBackgroundStatus().catch(() => ({})),
    ])
    genres.value = g.genres ?? []
    bgStatus.value = st
    if (genres.value.length && !activeGenre.value) onSelectGenre(genres.value[0])
  } catch { /* degraded */ }
}

async function onSelectGenre(g: string) {
  activeGenre.value = g
  loadingRules.value = true
  try {
    rules.value = await fetchSopGenreRules(g)
  } catch {
    rules.value = null
  } finally {
    loadingRules.value = false
  }
}

async function onReflect() {
  if (!activeGenre.value) return
  reflecting.value = true
  try {
    await triggerSopReflection(activeGenre.value)
    ElMessage.success(t('sop.reflectTriggered'))
    await onSelectGenre(activeGenre.value)
  } finally {
    reflecting.value = false
  }
}

async function toggleBackground() {
  if (bgStatus.value.running) {
    await stopSopBackground()
  } else {
    await startSopBackground()
  }
  bgStatus.value = await fetchSopBackgroundStatus().catch(() => ({}))
}

onMounted(load)
</script>

<style scoped>
.sop-view { padding: 24px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.bg-tag { margin-right: 8px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.rule-block { margin-bottom: 12px; }
.rule-block pre { background: var(--el-fill-color-light); padding: 8px; border-radius: 4px; overflow: auto; }
</style>
