<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '../stores/projects'
import { useChapterStore } from '../stores/chapters'
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const chapterStore = useChapterStore()
const { t } = useI18n()

const editing = ref(false)
const draftTitle = ref('')

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

function openVoiceClone() {
  router.push(`/projects/${projectId}/voice-clone`)
}

function openTranslation() {
  router.push(`/projects/${projectId}/translation`)
}

function openAgentChat() {
  router.push(`/projects/${projectId}/agent-chat`)
}

function openAutoRun() {
  router.push(`/projects/${projectId}/auto-run`)
}

function startEdit() {
  draftTitle.value = projectStore.currentProject?.title || ''
  editing.value = true
}

async function saveEdit() {
  const name = draftTitle.value.trim()
  const current = projectStore.currentProject?.title || ''
  if (!name || name === current) {
    editing.value = false
    return
  }
  try {
    await projectStore.editProject(projectId, { title: name } as any)
    editing.value = false
  } catch (e: any) {
    alert(t('projects.create_failed') + (e.message || e))
  }
}

function cancelEdit() {
  editing.value = false
  draftTitle.value = ''
}

function exportProject() {
  router.push(`/projects/${projectId}/export`)
}

function goBack() {
  router.push('/')
}

function getStatusBadgeClass(status: string): string {
  const map: Record<string, string> = {
    completed: 'badge-success',
    pending: 'badge-muted',
    processing: 'badge-warning',
    failed: 'badge-danger',
    error: 'badge-danger',
  }
  return map[status?.toLowerCase()] || 'badge-muted'
}

function formatStatus(status: string): string {
  const map: Record<string, string> = {
    completed: t('common.completed'),
    pending: t('common.pending'),
    processing: t('common.processing'),
    failed: t('common.failed'),
    error: t('common.error'),
  }
  return map[status?.toLowerCase()] || status
}
</script>

<template>
  <div class="page-container project-detail">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <h1>{{ projectStore.currentProject?.title || t('project_detail.title') }}</h1>
      <h1 v-if="editing" class="editing-title">
        <input
          v-model="draftTitle"
          class="form-control"
          :placeholder="t('projects.enter_project_name')"
          @keyup.enter="saveEdit"
          @keyup.esc="cancelEdit"
        />
        <button class="btn btn-primary btn-sm touch-target-sm" :title="t('common.save')" @click="saveEdit">
          <Icon icon="mdi:check" width="18" height="18" />
        </button>
        <button class="btn btn-ghost btn-sm touch-target-sm" :title="t('common.cancel')" @click="cancelEdit">
          <Icon icon="mdi:close" width="18" height="18" />
        </button>
      </h1>
      <div class="header-actions flex gap-2">
        <button class="btn btn-outline touch-target" @click="manageCharacters" :title="t('project_detail.characters')">
          <Icon icon="mdi:account-group" width="18" height="18" />
          <span class="hidden-mobile">{{ t('project_detail.characters') }}</span>
        </button>
        <button class="btn btn-outline touch-target" @click="viewQuality" :title="t('project_detail.quality_report')">
          <Icon icon="mdi:chart-bar" width="18" height="18" />
          <span class="hidden-mobile">{{ t('project_detail.quality_report') }}</span>
        </button>
        <button class="btn btn-outline touch-target" @click="openAgentChat" :title="t('project_detail.agent_chat')">
          <Icon icon="mdi:robot-outline" width="18" height="18" />
          <span class="hidden-mobile">{{ t('project_detail.agent_chat') }}</span>
        </button>
        <button class="btn btn-primary touch-target" @click="openAutoRun" :title="t('auto_run.title')">
          <Icon icon="mdi:play-circle-outline" width="18" height="18" />
          <span class="hidden-mobile">{{ t('auto_run.title') }}</span>
        </button>
        <button class="btn btn-primary touch-target" @click="openVoiceClone" :title="t('voice_clone.title')">
          <Icon icon="mdi:microphone" width="18" height="18" />
          <span class="hidden-mobile">{{ t('voice_clone.title') }}</span>
        </button>
        <button class="btn btn-outline touch-target" @click="openTranslation" :title="t('translation.title')">
          <Icon icon="mdi:translate" width="18" height="18" />
          <span class="hidden-mobile">{{ t('translation.title') }}</span>
        </button>
        <button v-if="!editing" class="btn btn-outline touch-target" @click="startEdit" :title="t('common.edit')">
          <Icon icon="mdi:pencil-outline" width="18" height="18" />
          <span class="hidden-mobile">{{ t('common.edit') }}</span>
        </button>
        <button class="btn btn-primary touch-target" @click="exportProject" :title="t('common.export')">
          <Icon icon="mdi:export" width="18" height="18" />
          <span class="hidden-mobile">{{ t('common.export') }}</span>
        </button>
      </div>
    </header>

    <div v-if="projectStore.loading" class="loading-state">
      <div class="spinner"></div>
      <span>{{ t('common.loading') }}</span>
    </div>

    <div v-else-if="projectStore.error" class="alert alert-error">
      {{ t('common.error') }}: {{ projectStore.error }}
    </div>

    <template v-else>
      <section class="chapter-list section">
        <div class="flex items-center justify-between mb-4">
          <h2 class="card-title">{{ t('project_detail.chapters') }}</h2>
          <span class="badge badge-muted">{{ chapterStore.chapters?.length ?? 0 }} {{ t('common.chapters') }}</span>
        </div>

        <div v-if="(chapterStore.chapters?.length ?? 0) === 0" class="empty-state">
          <Icon icon="mdi:book-outline" width="48" height="48" style="opacity: 0.4" />
          <p>{{ t('project_detail.no_chapters') }}</p>
          <button class="btn btn-primary mt-4" @click="router.push(`/projects/${projectId}/upload`)">
            <Icon icon="mdi:upload" width="16" height="16" />
            {{ t('project_detail.upload_first') }}
          </button>
        </div>

        <div v-else class="grid gap-3">
          <div
            v-for="ch in chapterStore.chapters"
            :key="ch.id"
            class="card card-hover grid-auto-fill"
            @click="openChapter(ch.id)"
          >
            <div class="chapter-info">
              <h3 class="card-title" style="font-size: 16px; margin: 0;">
                {{ ch.title || t('project_detail.chapter_fallback', { number: ch.chapter_number || ch.id }) }}
              </h3>
              <span :class="getStatusBadgeClass(ch.status || 'pending')">{{ formatStatus(ch.status || 'pending') }}</span>
            </div>
            <Icon icon="mdi:chevron-right" width="24" height="24" class="chevron" />
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.project-detail {
  max-width: 960px;
}
.chapter-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}
.chapter-info h3 {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chevron {
  color: var(--color-text-muted);
  flex-shrink: 0;
}
.header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.editing-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.editing-title .form-control {
  flex: 1;
  min-width: 0;
}

@media (max-width: 767px) {
  .header-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .page-header h1 {
    font-size: 20px;
  }
}
</style>
