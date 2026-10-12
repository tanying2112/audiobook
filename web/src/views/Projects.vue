<script setup lang="ts">
import { computed, ref, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '../stores/projects'
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'
import EmptyState from '../components/EmptyState.vue'
import ProjectCard from '../components/ProjectCard.vue'
import { ElMessageBox, ElMessage } from 'element-plus'

const router = useRouter()
const store = useProjectStore()
const { t } = useI18n()

// ── 搜索 ─────────────────────────────────────────────────────
const searchQuery = ref('')

// ── 创建项目 Dialog ──────────────────────────────────────────
const createDialogVisible = ref(false)
const createForm = reactive({
  title: '', author: '', description: '', language: '', genre: '', difficulty: '',
})
const createLoading = ref(false)

function openCreateDialog() {
  Object.assign(createForm, { title: '', author: '', description: '', language: '', genre: '', difficulty: '' })
  createDialogVisible.value = true
}

async function submitCreate() {
  const title = createForm.title.trim()
  if (!title) { ElMessage.warning(t('projects.enter_project_name')); return }
  createLoading.value = true
  try {
    await store.addProject({
      title, author: createForm.author.trim() || undefined,
      description: createForm.description.trim() || undefined,
      language: createForm.language || undefined,
      genre: createForm.genre || undefined,
      difficulty: createForm.difficulty || undefined,
    } as any)
    createDialogVisible.value = false
    ElMessage.success('Created')
  } catch (e: any) {
    ElMessage.error(t('projects.create_failed') + (e.message || e))
  } finally {
    createLoading.value = false
  }
}

// ── 删除 ─────────────────────────────────────────────────────
async function removeProject(id: number, title: string) {
  try {
    await ElMessageBox.confirm(
      t('projects.delete_confirm', { title }),
      t('projects.delete_tooltip'),
      { confirmButtonText: 'OK', cancelButtonText: t('common.cancel'), type: 'warning' },
    )
  } catch { return }
  try {
    await store.removeProject(id)
    ElMessage.success('Deleted')
  } catch (e: any) {
    ElMessage.error(t('projects.delete_failed') + (e.message || e))
  }
}

// ── 编辑标题 ─────────────────────────────────────────────────
const editingId = ref<number | null>(null)
const draftTitle = ref('')

function startEditTitle(id: number, currentTitle: string) {
  draftTitle.value = currentTitle; editingId.value = id
}

async function saveEdit(id: number) {
  const name = draftTitle.value.trim()
  const idx = store.projects.findIndex((p) => p.id === id)
  const current = idx !== -1 ? (store.projects[idx].title || '') : ''
  if (!name || name === current) { editingId.value = null; return }
  try { await store.editProject(id, { title: name } as any); editingId.value = null }
  catch (e: any) { ElMessage.error(t('projects.create_failed') + (e.message || e)) }
}

function cancelEdit() { editingId.value = null; draftTitle.value = '' }

// ── 过滤 & 排序(默认按最近活动) ───────────────────────────────
const filteredProjects = computed(() => {
  const q = searchQuery.value.toLowerCase()
  const list = Array.isArray(store.projects) ? [...store.projects] : []
  const result = q
    ? list.filter((p) =>
        (p.title || '').toLowerCase().includes(q) ||
        (p.author || '').toLowerCase().includes(q) ||
        (p.description || '').toLowerCase().includes(q) ||
        (p.genre || '').toLowerCase().includes(q))
    : list
  result.sort((a, b) => {
    const da = new Date(a.updated_at || a.created_at || 0).getTime()
    const db = new Date(b.updated_at || b.created_at || 0).getTime()
    return db - da
  })
  return result
})

// ── 导航 ──────────────────────────────────────────────────────
function openProject(id: number) { router.push(`/projects/${id}`) }
function exportProject(id: number) { router.push(`/projects/${id}/export`) }
function openAutoRun(id: number) { router.push(`/projects/${id}/auto-run`) }
function openQuality(id: number) { router.push(`/projects/${id}/quality`) }
function openTranslation(id: number) { router.push(`/projects/${id}/translation`) }
function openCharacters(id: number) { router.push(`/projects/${id}/characters`) }

onMounted(() => store.loadProjects())
</script>

<template>
  <div class="page-container">
    <header class="page-header">
      <h1>{{ t('projects.title') }}</h1>
      <button class="btn btn-primary touch-target" @click="openCreateDialog">
        <Icon icon="mdi:plus" width="18" height="18" />
        <span class="hidden-mobile">{{ t('projects.new_project') }}</span>
      </button>
    </header>

    <div class="search-bar section">
      <Icon icon="mdi:magnify" width="18" height="18" class="search-icon" />
      <input v-model="searchQuery" type="text" :placeholder="t('projects.search_placeholder')" class="form-control search-input" />
    </div>

    <div v-if="store.loading" class="loading-section">
      <div class="spinner"></div>
      <p>{{ t('projects.loading') }}</p>
    </div>

    <div v-else-if="store.error" class="alert alert-error">
      {{ t('common.error') }}: {{ store.error }}
    </div>

    <EmptyState
      v-else-if="filteredProjects.length === 0"
      :icon="searchQuery ? 'mdi:magnify-close' : 'mdi:bookshelf'"
      :title="searchQuery ? t('projects.no_results') : t('projects.empty_state')"
      :description="searchQuery ? t('projects.search_placeholder') : undefined"
    >
      <button v-if="!searchQuery" class="btn btn-primary touch-target" @click="openCreateDialog">
        <Icon icon="mdi:plus" width="18" height="18" />
        <span>{{ t('projects.new_project') }}</span>
      </button>
    </EmptyState>

    <div v-else class="project-grid">
      <ProjectCard
        v-for="project in filteredProjects"
        :key="project.id"
        :project="project"
        :editing="editingId === project.id"
        :draft-title="draftTitle"
        @open="openProject"
        @delete="removeProject"
        @edit-title="startEditTitle"
        @save-edit="saveEdit"
        @cancel-edit="cancelEdit"
        @update:draft="(v: string) => (draftTitle = v)"
        @export="exportProject"
        @auto-run="openAutoRun"
        @characters="openCharacters"
        @quality="openQuality"
        @translation="openTranslation"
      />
    </div>

    <el-dialog v-model="createDialogVisible" :title="t('projects.new_project')" width="520px" :close-on-click-modal="false" destroy-on-close>
      <el-form label-position="top" @submit.prevent="submitCreate">
        <el-form-item :label="t('projects.project_name')" required>
          <el-input v-model="createForm.title" :placeholder="t('projects.enter_project_name')" autofocus @keyup.enter="submitCreate" />
        </el-form-item>
        <el-form-item label="Author">
          <el-input v-model="createForm.author" placeholder="Author" />
        </el-form-item>
        <el-form-item :label="t('projects.project_description')">
          <el-input v-model="createForm.description" type="textarea" :rows="3" placeholder="Description" />
        </el-form-item>
        <div class="form-row">
          <el-form-item label="Language" class="form-row__item">
            <el-select v-model="createForm.language" placeholder="Language" clearable>
              <el-option label="中文" value="zh" />
              <el-option label="English" value="en" />
              <el-option label="日本語" value="ja" />
            </el-select>
          </el-form-item>
          <el-form-item label="Genre" class="form-row__item">
            <el-select v-model="createForm.genre" placeholder="Genre" clearable>
              <el-option v-for="g in ['古典小说','现代小说','武侠小说','科幻小说','奇幻小说','历史小说','悬疑小说','言情小说','传记文学','散文随笔','儿童文学','其他']" :key="g" :label="g" :value="g" />
            </el-select>
          </el-form-item>
          <el-form-item label="Difficulty" class="form-row__item">
            <el-select v-model="createForm.difficulty" placeholder="Difficulty" clearable>
              <el-option label="初级" value="easy" />
              <el-option label="中级" value="medium" />
              <el-option label="高级" value="hard" />
            </el-select>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="createLoading" @click="submitCreate">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.search-bar { position: relative; }
.search-icon {
  position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
  color: var(--color-text-muted); pointer-events: none;
}
.search-input { padding-left: 40px !important; }

.project-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px;
}

.loading-section {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; padding: 48px 24px; color: var(--color-text-secondary); text-align: center;
}

.form-row { display: flex; gap: 12px; }
.form-row__item { flex: 1; min-width: 0; }

@media (max-width: 767px) {
  .project-grid { grid-template-columns: 1fr; }
  .form-row { flex-direction: column; gap: 0; }
}
</style>
