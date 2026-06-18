<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChapterStore } from '../stores/chapters'
import { Icon } from '@iconify/vue'

const route = useRoute()
const router = useRouter()
const store = useChapterStore()

const projectId = Number(route.params.projectId)
const filterStatus = ref<string>('all')

onMounted(async () => {
  await store.loadChapters(projectId)
})

const filteredChapters = computed(() => {
  if (filterStatus.value === 'all') return store.chapters
  return store.chapters.filter((ch) => (ch.status || 'pending') === filterStatus.value)
})

const stats = computed(() => {
  const total = store.chapters.length
  const completed = store.chapters.filter((ch) => ch.status === 'completed').length
  const error = store.chapters.filter((ch) => ch.status === 'error').length
  const pending = total - completed - error
  const completionRate = total > 0 ? Math.round((completed / total) * 100) : 0
  return { total, completed, error, pending, completionRate }
})
</script>

<template>
  <div class="quality-report">
    <div class="page-header">
      <button class="btn btn-ghost" @click="router.push(`/projects/${projectId}`)">
        <Icon icon="mdi:arrow-left" width="18" height="18" /> 返回
      </button>
      <h1>质量报告</h1>
    </div>

    <section class="summary-cards">
      <div class="summary-card accent">
        <span class="summary-value">{{ stats.total }}</span>
        <span class="summary-label">总章节</span>
      </div>
      <div class="summary-card">
        <span class="summary-value success">{{ stats.completed }}</span>
        <span class="summary-label">已完成</span>
      </div>
      <div class="summary-card">
        <span class="summary-value warning">{{ stats.pending }}</span>
        <span class="summary-label">待检查</span>
      </div>
      <div class="summary-card">
        <span class="summary-value danger">{{ stats.error }}</span>
        <span class="summary-label">异常</span>
      </div>
    </section>

    <section class="completion-bar-section">
      <div class="completion-header">
        <span>整体完成度</span>
        <span class="completion-pct">{{ stats.completionRate }}%</span>
      </div>
      <div class="completion-track">
        <div class="completion-fill" :style="{ width: stats.completionRate + '%' }"></div>
      </div>
    </section>

    <section class="filter-bar">
      <button
        v-for="opt in [['all', '全部'], ['completed', '已完成'], ['pending', '待处理'], ['error', '异常']]"
        :key="opt[0]"
        :class="['filter-btn', { active: filterStatus === opt[0] }]"
        @click="filterStatus = opt[0]"
      >{{ opt[1] }}</button>
    </section>

    <section class="chapter-quality-list">
      <div v-if="filteredChapters.length === 0" class="empty">暂无数据</div>
      <div
        v-for="ch in filteredChapters"
        :key="ch.id"
        class="quality-row"
      >
        <div class="quality-row-info">
          <Icon
            :icon="ch.status === 'completed' ? 'mdi:check-circle' : ch.status === 'error' ? 'mdi:alert-circle' : 'mdi:clock-outline'"
            :class="['status-icon', ch.status || 'pending']"
            width="20"
            height="20"
          />
          <span class="quality-row-title">{{ ch.title || `第 ${ch.chapter_number || ch.id} 章` }}</span>
        </div>
        <div class="quality-row-meta">
          <span :class="['badge', ch.status || 'pending']">{{ ch.status || 'pending' }}</span>
          <button
            class="btn btn-ghost btn-sm"
            @click="router.push(`/projects/${projectId}/chapters/${ch.id}`)"
          >
            查看详情
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.quality-report { max-width: 860px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; }
.page-header h1 { margin: 0; font-size: 22px; flex: 1; }
.summary-cards { display: flex; gap: 12px; margin-bottom: 20px; }
.summary-card {
  flex: 1;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px 16px;
  text-align: center;
}
.summary-card.accent { border-color: #bfdbfe; background: #eff6ff; }
.summary-value { display: block; font-size: 28px; font-weight: 700; color: #1e293b; }
.summary-value.success { color: #22c55e; }
.summary-value.warning { color: #f59e0b; }
.summary-value.danger { color: #ef4444; }
.summary-label { font-size: 12px; color: #64748b; margin-top: 2px; }
.completion-bar-section { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }
.completion-header { display: flex; justify-content: space-between; font-size: 14px; font-weight: 500; margin-bottom: 8px; }
.completion-pct { color: #3b82f6; font-weight: 600; }
.completion-track { height: 8px; background: #e2e8f0; border-radius: 99px; overflow: hidden; }
.completion-fill { height: 100%; background: linear-gradient(90deg, #3b82f6, #22c55e); border-radius: 99px; transition: width 0.3s; }
.filter-bar { display: flex; gap: 6px; margin-bottom: 12px; }
.filter-btn {
  padding: 4px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 99px;
  background: #fff;
  font-size: 13px;
  cursor: pointer;
  color: #64748b;
  transition: all 0.15s;
}
.filter-btn:hover { border-color: #93c5fd; color: #1d4ed8; }
.filter-btn.active { background: #3b82f6; color: #fff; border-color: #3b82f6; }
.quality-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  margin-bottom: 6px;
}
.quality-row-info { display: flex; align-items: center; gap: 10px; }
.quality-row-title { font-size: 14px; font-weight: 500; }
.quality-row-meta { display: flex; align-items: center; gap: 8px; }
.status-icon.completed { color: #22c55e; }
.status-icon.error { color: #ef4444; }
.status-icon.pending { color: #f59e0b; }
.badge { font-size: 11px; padding: 2px 10px; border-radius: 99px; text-transform: uppercase; }
.badge.completed { background: #dcfce7; color: #16a34a; }
.badge.pending { background: #fef9c3; color: #ca8a04; }
.badge.error { background: #fee2e2; color: #dc2626; }
.empty { text-align: center; padding: 40px; color: #64748b; }
.btn-sm { padding: 4px 10px; font-size: 12px; }
</style>