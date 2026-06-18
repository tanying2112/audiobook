<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '../stores/projects'
import { Icon } from '@iconify/vue'

const router = useRouter()
const store = useProjectStore()
const searchQuery = ref('')

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
  const name = prompt('请输入项目名称:')
  if (!name) return
  try {
    await store.addProject({ title: name } as any)
  } catch (e: any) {
    alert('创建失败: ' + (e.message || e))
  }
}

async function removeProject(id: number, title: string) {
  if (!confirm(`确定删除项目「${title}」？此操作不可撤销。`)) return
  try {
    await store.removeProject(id)
  } catch (e: any) {
    alert('删除失败: ' + (e.message || e))
  }
}
</script>

<template>
  <div class="projects-page">
    <div class="page-header">
      <h1>项目列表</h1>
      <button class="btn btn-primary" @click="createProject">
        <Icon icon="mdi:plus" width="18" height="18" />
        新建项目
      </button>
    </div>

    <div class="search-bar">
      <Icon icon="mdi:magnify" width="18" height="18" class="search-icon" />
      <input
        v-model="searchQuery"
        type="text"
        placeholder="搜索项目名称或描述..."
        class="search-input"
      />
    </div>

    <div v-if="store.loading" class="loading">加载中...</div>
    <div v-else-if="store.error" class="error">{{ store.error }}</div>
    <div v-else-if="filteredProjects.length === 0" class="empty">
      {{ searchQuery ? '未找到匹配的项目' : '暂无项目，点击"新建项目"开始使用。' }}
    </div>

    <div v-else class="project-grid">
      <div
        v-for="project in filteredProjects"
        :key="project.id"
        class="project-card"
        @click="openProject(project.id)"
      >
        <div class="card-body">
          <h3>{{ project.title || '未命名项目' }}</h3>
          <p v-if="project.description" class="desc">{{ project.description }}</p>
          <span class="meta">ID: {{ project.id }}</span>
        </div>
        <div class="card-actions">
          <button class="btn-icon" title="删除" @click.stop="removeProject(project.id, project.title || '')">
            <Icon icon="mdi:delete-outline" width="18" height="18" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.projects-page { max-width: 960px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h1 { margin: 0; font-size: 24px; }
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 20px;
}
.search-icon { color: #94a3b8; flex-shrink: 0; }
.search-input {
  border: none;
  outline: none;
  flex: 1;
  font-size: 14px;
  background: transparent;
  color: var(--color-text);
}
.search-input::placeholder { color: #94a3b8; }
.project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.project-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.15s;
  display: flex;
  justify-content: space-between;
}
.project-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); transform: translateY(-2px); }
.card-body h3 { margin: 0 0 8px; font-size: 18px; }
.desc { color: #64748b; font-size: 14px; margin: 0 0 8px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.meta { color: #94a3b8; font-size: 12px; }
.card-actions { display: flex; align-items: flex-start; }
.btn-icon { background: none; border: none; cursor: pointer; color: #94a3b8; padding: 4px; border-radius: 6px; }
.btn-icon:hover { background: #fee2e2; color: #ef4444; }
.loading, .error, .empty { text-align: center; padding: 60px 20px; color: #64748b; }
.error { color: #ef4444; }
</style>