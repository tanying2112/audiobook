<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '../stores/projects'
import { useChapterStore } from '../stores/chapters'
import { Icon } from '@iconify/vue'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const chapterStore = useChapterStore()

const projectId = Number(route.params.id)

onMounted(async () => {
  await projectStore.loadProject(projectId)
  await chapterStore.loadChapters(projectId)
})

function openChapter(chapterId: number) {
  router.push(`/projects/${projectId}/chapters/${chapterId}`)
}

function manageCharacters() {
  router.push(`/projects/${projectId}/characters`)
}

function viewQuality() {
  router.push(`/projects/${projectId}/quality`)
}
</script>

<template>
  <div class="project-detail">
    <div class="page-header">
      <button class="btn btn-ghost" @click="router.push('/')">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        返回
      </button>
      <h1>{{ projectStore.currentProject?.title || '项目详情' }}</h1>
      <div class="header-actions">
        <button class="btn btn-outline" @click="manageCharacters">
          <Icon icon="mdi:account-group" width="18" height="18" />
          角色管理
        </button>
        <button class="btn btn-outline" @click="viewQuality">
          <Icon icon="mdi:chart-bar" width="18" height="18" />
          质量报告
        </button>
      </div>
    </div>

    <div v-if="projectStore.loading" class="loading">加载中...</div>
    <template v-else>
      <section class="chapter-list">
        <h2>章节列表</h2>
        <div v-if="chapterStore.chapters.length === 0" class="empty">暂无章节</div>
        <div
          v-for="ch in chapterStore.chapters"
          :key="ch.id"
          class="chapter-card"
          @click="openChapter(ch.id)"
        >
          <div class="chapter-info">
            <h3>{{ ch.title || `第 ${ch.chapter_number || ch.id} 章` }}</h3>
            <span class="badge">{{ ch.status || 'pending' }}</span>
          </div>
          <Icon icon="mdi:chevron-right" width="24" height="24" class="chevron" />
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.project-detail { max-width: 960px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.page-header h1 { margin: 0; font-size: 22px; flex: 1; }
.header-actions { display: flex; gap: 8px; }
.chapter-list h2 { font-size: 18px; margin: 0 0 12px; }
.chapter-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.chapter-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.chapter-info { display: flex; align-items: center; gap: 12px; }
.chapter-info h3 { margin: 0; font-size: 16px; }
.badge {
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 99px;
  background: #dbeafe;
  color: #1d4ed8;
  text-transform: uppercase;
}
.chevron { color: #94a3b8; }
.loading, .empty { text-align: center; padding: 40px; color: #64748b; }
</style>