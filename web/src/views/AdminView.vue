<template>
  <div class="admin-view page-container">
    <div class="page-header">
      <h1>{{ t('admin.title') }}</h1>
    </div>

    <div class="card section" v-loading="loadingUsers">
      <div class="card-header">
        <span class="card-title">{{ t('admin.users') }}</span>
        <button class="btn btn-outline btn-sm" @click="loadUsers" :aria-label="t('common.refresh')">{{ t('common.refresh') }}</button>
      </div>
      <div class="table-responsive">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>{{ t('admin.username') }}</th>
              <th>{{ t('admin.email') }}</th>
              <th>{{ t('admin.roles') }}</th>
              <th>{{ t('admin.active') }}</th>
              <th>{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>{{ user.id }}</td>
              <td>{{ user.username }}</td>
              <td>{{ user.email }}</td>
              <td class="roles-cell">
                <span
                  v-for="role in user.roles || []"
                  :key="role"
                  class="badge badge-info role-tag"
                >
                  {{ role }}
                  <button
                    class="badge-dismiss"
                    @click="onRevokeRole(user, role)"
                    :aria-label="`Remove role ${role}`"
                  >&times;</button>
                </span>
                <el-dropdown trigger="click" @command="(r: string) => onAssignRole(user, r)">
                  <button class="btn btn-ghost btn-sm">+ {{ t('admin.assignRole') }}</button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item
                        v-for="role in availableRoles(user)"
                        :key="role"
                        :command="role"
                      >{{ role }}</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </td>
              <td>
                <el-switch
                  :model-value="user.is_active"
                  @change="(v: boolean) => onToggleActive(user, v)"
                />
              </td>
              <td>
                <el-popconfirm :title="t('admin.deleteConfirm')" @confirm="onDelete(user)">
                  <template #reference>
                    <button class="btn btn-ghost btn-sm text-danger">{{ t('common.delete') }}</button>
                  </template>
                </el-popconfirm>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="usersError" class="alert alert-error mt-4">
        {{ usersError }}
      </div>
    </div>

    <div class="card section">
      <div class="card-header">
        <span class="card-title">{{ t('admin.systemConfig') }}</span>
        <button class="btn btn-outline btn-sm" :disabled="reloading" @click="onReloadConfig" :aria-label="t('admin.reloadConfig')">
          <span v-if="reloading" class="spinner"></span>
          {{ t('admin.reloadConfig') }}
        </button>
      </div>
      <el-descriptions v-if="configStatus" :column="2" border size="small">
        <el-descriptions-item v-for="(v, k) in configStatus" :key="k" :label="String(k)">
          {{ typeof v === 'object' ? JSON.stringify(v) : String(v) }}
        </el-descriptions-item>
      </el-descriptions>
      <div v-else class="empty-state">
        <p>{{ t('admin.noConfigInfo') }}</p>
      </div>
    </div>
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
  /* max-width & margin handled by .page-container */
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.roles-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.role-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.badge-dismiss {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0;
  opacity: 0.6;
  transition: opacity var(--transition-fast);
}

.badge-dismiss:hover {
  opacity: 1;
}

@media (max-width: 767px) {
  .card-header {
    flex-direction: column;
    gap: 12px;
    align-items: stretch;
  }

  .roles-cell {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
