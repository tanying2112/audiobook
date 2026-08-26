<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '../stores/projects'
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'

const router = useRouter()
const store = useProjectStore()
const searchQuery = ref('')
const { t } = useI18n()

onMounted(() => store.loadProjects())

const filteredProjects = computed(() => {
  const q = searchQuery.value.toLowerCase()
  if (!q) return store.projects
  return store.projects.filter(
    (p) =>
      (p.title || '').toLowerCase().includes(q) ||
      (p.description || '').toLowerCase().includes(q),
  )
})

function openProject(id: number) {
  router.push(`/projects/${id}`)
}

async function createProject() {
  const name = prompt(t('projects.enter_project_name'))
  if (!name) return
  try {
    await store.addProject({ title: name } as any)
  } catch (e: any) {
    alert(t('projects.create_failed') + (e.message || e))
  }
}

async function removeProject(id: number, title: string) {
  if (!confirm(t('projects.delete_confirm', { title }))) return
  try {
    await store.removeProject(id)
  } catch (e: any) {
    alert(t('projects.delete_failed') + (e.message || e))
  }
}
</script>

<template>
  <div class="page-container">
    <header class="page-header">
      <h1>{{ t('projects.title') }}</h1>
      <button class="btn btn-primary touch-target" @click="createProject">
        <Icon icon="mdi:plus" width="18" height="18" />
        <span class="hidden-mobile">{{ t('projects.new_project') }}</span>
      </button>
    </header>

    <div class="search-bar section">
      <Icon icon="mdi:magnify" width="18" height="18" class="search-icon" />
      <input
        v-model="searchQuery"
        type="text"
        :placeholder="t('projects.search_placeholder')"
        class="form-control search-input"
      />
    </div>

    <div v-if="store.loading" class="loading-section">
      <div class="spinner"></div>
      <p>{{ t('projects.loading') }}</p>
    </div>
    <div v-else-if="store.error" class="alert alert-error">
      {{ t('common.error') }}: {{ store.error }}
    </div>
    <div v-else-if="filteredProjects.length === 0" class="empty-state">
      {{ searchQuery ? t('projects.no_results') : t('projects.empty_state') }}
    </div>

    <div v-else class="grid grid-auto-fill">
      <div
        v-for="project in filteredProjects"
        :key="project.id"
        class="card card-hover touch-target"
        @click="openProject(project.id)"
      >
        <div class="card-body">
          <h3 class="card-title">{{ project.title || t('projects.unnamed_project') }}</h3>
          <p v-if="project.description" class="desc">{{ project.description }}</p>
          <span class="meta">{{ t('projects.project_id', { id: project.id }) }}</span>
        </div>
        <div class="card-actions">
          <button class="btn btn-ghost btn-sm touch-target-sm" :title="t('projects.delete_tooltip')" @click.stop="removeProject(project.id, project.title || '')">
            <Icon icon="mdi:delete-outline" width="18" height="18" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Uses global responsive utilities from style.css */

.search-bar {
  position: relative;
}
.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  pointer-events: none;
}
.search-input {
  padding-left: 40px !important;
}

.project-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  cursor: pointer;
  transition: box-shadow var(--transition), transform var(--transition-fast);
}
.project-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}
.project-card:active {
  transform: translateY(0);
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card-title {
  margin: 0;
  font-size: 17px;
}
.desc {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 14px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  color: var(--color-text-muted);
  font-size: 12px;
}

.card-actions {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.loading-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px 24px;
  color: var(--color-text-secondary);
  text-align: center;
}
</style>