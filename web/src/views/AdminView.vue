<template>
  <div class="admin-view">
    <h1>{{ t('admin.title') }}</h1>

    <el-card class="section" v-loading="loadingUsers">
      <template #header>
        <div class="card-header">
          <span>{{ t('admin.users') }}</span>
          <el-button size="small" @click="loadUsers">{{ t('common.refresh') }}</el-button>
        </div>
      </template>
      <el-table :data="users" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" :label="t('admin.username')" />
        <el-table-column prop="email" :label="t('admin.email')" />
        <el-table-column :label="t('admin.roles')">
          <template #default="{ row }">
            <el-tag
              v-for="role in row.roles || []"
              :key="role"
              size="small"
              closable
              class="role-tag"
              @close="onRevokeRole(row, role)"
            >{{ role }}</el-tag>
            <el-dropdown trigger="click" @command="(r: string) => onAssignRole(row, r)">
              <el-button size="small" text type="primary">+ {{ t('admin.assignRole') }}</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="role in availableRoles(row)"
                    :key="role"
                    :command="role"
                  >{{ role }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <el-table-column :label="t('admin.active')" width="110">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_active"
              @change="(v: boolean) => onToggleActive(row, v)"
            />
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="120">
          <template #default="{ row }">
            <el-popconfirm :title="t('admin.deleteConfirm')" @confirm="onDelete(row)">
              <template #reference>
                <el-button size="small" type="danger" text>{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-alert
        v-if="usersError"
        :title="usersError"
        type="error"
        :closable="false"
        class="mt"
      />
    </el-card>

    <el-card class="section">
      <template #header>
        <div class="card-header">
          <span>{{ t('admin.systemConfig') }}</span>
          <el-button size="small" type="warning" :loading="reloading" @click="onReloadConfig">
            {{ t('admin.reloadConfig') }}
          </el-button>
        </div>
      </template>
      <el-descriptions v-if="configStatus" :column="2" border size="small">
        <el-descriptions-item v-for="(v, k) in configStatus" :key="k" :label="String(k)">
          {{ typeof v === 'object' ? JSON.stringify(v) : String(v) }}
        </el-descriptions-item>
      </el-descriptions>
      <el-empty v-else :description="t('admin.noConfigInfo')" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from '../i18n'
import {
  fetchUsers,
  fetchRoles,
  updateUser,
  deleteUser,
  assignRole,
  revokeRole,
  reloadAllConfig,
  fetchConfigStatus,
  type AdminUser,
  type AdminRole,
} from '../api/admin'

const { t } = useI18n()

const users = ref<AdminUser[]>([])
const roles = ref<AdminRole[]>([])
const configStatus = ref<Record<string, unknown> | null>(null)
const loadingUsers = ref(false)
const reloading = ref(false)
const usersError = ref('')

function availableRoles(user: AdminUser): string[] {
  const owned = new Set(user.roles || [])
  return roles.value.map((r) => r.name).filter((n) => !owned.has(n))
}

async function loadUsers() {
  loadingUsers.value = true
  usersError.value = ''
  try {
    users.value = await fetchUsers()
  } catch (e: unknown) {
    usersError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loadingUsers.value = false
  }
}

async function onToggleActive(user: AdminUser, active: boolean) {
  try {
    await updateUser(user.id, { is_active: active })
    user.is_active = active
    ElMessage.success(t('admin.updated'))
  } catch {
    ElMessage.error(t('admin.updateFailed'))
  }
}

async function onAssignRole(user: AdminUser, role: string) {
  try {
    await assignRole(user.id, role)
    user.roles = [...(user.roles || []), role]
    ElMessage.success(t('admin.roleAssigned'))
  } catch {
    ElMessage.error(t('admin.updateFailed'))
  }
}

async function onRevokeRole(user: AdminUser, role: string) {
  try {
    await revokeRole(user.id, role)
    user.roles = (user.roles || []).filter((r) => r !== role)
    ElMessage.success(t('admin.roleRevoked'))
  } catch {
    ElMessage.error(t('admin.updateFailed'))
  }
}

async function onDelete(user: AdminUser) {
  try {
    await deleteUser(user.id)
    users.value = users.value.filter((u) => u.id !== user.id)
    ElMessage.success(t('admin.deleted'))
  } catch {
    ElMessage.error(t('admin.updateFailed'))
  }
}

async function onReloadConfig() {
  reloading.value = true
  try {
    await reloadAllConfig()
    configStatus.value = await fetchConfigStatus()
    ElMessage.success(t('admin.configReloaded'))
  } catch {
    ElMessage.error(t('admin.updateFailed'))
  } finally {
    reloading.value = false
  }
}

onMounted(async () => {
  await Promise.all([
    loadUsers(),
    fetchRoles().then((r) => (roles.value = r)).catch(() => {}),
    fetchConfigStatus().then((s) => (configStatus.value = s)).catch(() => {}),
  ])
})
</script>

<style scoped>
.admin-view {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}
.section {
  margin-bottom: 24px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.role-tag {
  margin-right: 6px;
}
.mt {
  margin-top: 12px;
}
</style>
