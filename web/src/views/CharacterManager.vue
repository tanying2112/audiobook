<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as api from '../api'
import type { Character, BookGenre } from '../types'
import { useSopCorrection } from '../composables/useSopCorrection'
import { useI18n } from '../i18n'
import { Icon } from '@iconify/vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = Number(route.params.projectId)

const characters = ref<Character[]>([])
const loading = ref(false)
const editingChar = ref<Character | null>(null)
const showEditor = ref(false)

// Form state
const formName = ref('')
const formVoice = ref('')
const formEmotion = ref('neutral')
const formPitch = ref(0)
const formSpeed = ref(1.0)

// SOP correction capture
const genre = ref<BookGenre>('')
let sendCorrection: ((
  field: string,
  originalValue: string,
  correctedValue: string,
  paragraphIndex: number,
  chapterIndex: number,
  context?: string,
) => Promise<boolean>) | null = null

onMounted(async () => {
  loading.value = true
  try {
    const [chars, project] = await Promise.all([
      api.fetchCharacters(projectId),
      api.fetchProject(projectId),
    ])
    characters.value = chars
    if (project?.genre) genre.value = project.genre as BookGenre

    sendCorrection = useSopCorrection({
      projectId,
      genre: genre.value,
      autoConnect: true,
      onFallback: (reason) => console.warn('[SOP CharacterManager] HTTP 回退:', reason),
    }).sendCorrection
  } finally {
    loading.value = false
  }
})

function addCharacter() {
  formName.value = ''
  formVoice.value = ''
  formEmotion.value = 'neutral'
  formPitch.value = 0
  formSpeed.value = 1.0
  editingChar.value = null
  showEditor.value = true
}

function editCharacter(c: Character) {
  formName.value = c.canonical_name || ''
  formVoice.value = c.suggested_voice_id || ''
  formEmotion.value = 'neutral'
  formPitch.value = 0
  formSpeed.value = 1.0
  editingChar.value = c
  showEditor.value = true
}

async function saveCharacter() {
  if (!formName.value.trim()) return
  const payload = {
    canonical_name: formName.value.trim(),
    suggested_voice_id: formVoice.value || undefined,
  } as any

  try {
    const wasEditing = !!editingChar.value
    const origName = editingChar.value?.canonical_name ?? ''
    const origVoice = editingChar.value?.suggested_voice_id ?? ''
    const newName = payload.canonical_name ?? ''
    const newVoice = payload.suggested_voice_id ?? ''

    if (editingChar.value) {
      const updated = await api.updateCharacter(projectId, editingChar.value.id!, payload)
      const idx = characters.value.findIndex((c) => c.id === updated.id)
      if (idx !== -1) characters.value[idx] = updated
    } else {
      const created = await api.createCharacter(projectId, payload)
      characters.value.push(created)
    }
    showEditor.value = false

    if (wasEditing) {
      if (origName && origName !== newName) {
        feedSop('speaker_canonical_name', origName, newName, `CharacterManager: 角色改名 "${origName}"→"${newName}"`)
      }
      if (origVoice !== newVoice) {
        feedSop(
          'suggested_voice_id',
          origVoice,
          newVoice,
          `CharacterManager: 角色 "${newName || origName}" 声音绑定变更`,
        )
      }
    }
  } catch (e: any) {
    alert(t('character_manager.save_failed') + (e.message || e))
  }
}

function feedSop(field: string, originalValue: string, correctedValue: string, context: string) {
  if (!sendCorrection) return
  void sendCorrection(field, originalValue, correctedValue, 0, 0, context).catch((e) => {
    console.warn('[SOP CharacterManager] 投喂失败（静默降级）:', e?.message || e)
  })
}

async function removeCharacter(id: number) {
  if (!confirm(t('character_manager.delete_confirm'))) return
  try {
    await api.deleteCharacter(projectId, id)
    characters.value = characters.value.filter((c) => c.id !== id)
  } catch (e: any) {
    alert(t('character_manager.delete_failed') + (e.message || e))
  }
}

function goBack() {
  router.push(`/projects/${projectId}`)
}
</script>

<template>
  <div class="page-container character-manager">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <h1>{{ t('character_manager.title') }}</h1>
      <button class="btn btn-primary touch-target" @click="addCharacter">
        <Icon icon="mdi:account-plus" width="18" height="18" class="gap-2" />
        {{ t('character_manager.add_character') }}
      </button>
    </header>

    <div v-if="loading" class="loading-state section">
      <div class="spinner"></div>
      <span>{{ t('character_manager.loading') }}</span>
    </div>

    <template v-else>
      <div v-if="characters.length === 0" class="empty-state section">
        <Icon icon="mdi:account-group-outline" width="48" height="48" style="opacity: 0.4" />
        <p>{{ t('character_manager.empty') }}</p>
        <button class="btn btn-primary mt-4" @click="addCharacter">
          <Icon icon="mdi:account-plus" width="16" height="16" class="gap-2" />
          {{ t('character_manager.add_character') }}
        </button>
      </div>

      <div v-else class="character-list grid gap-3 section">
        <div
          v-for="c in characters"
          :key="c.id"
          class="card card-hover character-card flex items-center justify-between"
        >
          <div class="character-info flex items-center gap-3">
            <div class="character-avatar" style="width: 40px; height: 40px; border-radius: 50%; background: var(--color-primary-soft); color: var(--color-primary); display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 16px;">
              {{ c.canonical_name?.charAt(0).toUpperCase() || '?' }}
            </div>
            <div>
              <div class="character-name font-medium">{{ c.canonical_name }}</div>
              <div v-if="c.suggested_voice_id" class="character-voice text-muted text-sm">
                <Icon icon="mdi:microphone" width="14" height="14" class="inline gap-1" />
                {{ c.suggested_voice_id }}
              </div>
            </div>
          </div>
          <div class="character-actions flex gap-2">
            <button class="btn btn-ghost btn-sm touch-target" @click="editCharacter(c)" :title="t('character_manager.edit')">
              <Icon icon="mdi:pencil" width="16" height="16" />
              <span class="hidden-mobile">{{ t('character_manager.edit') }}</span>
            </button>
            <button class="btn btn-ghost btn-sm btn-danger touch-target" @click="removeCharacter(c.id!)" :title="t('character_manager.delete')">
              <Icon icon="mdi:delete-outline" width="16" height="16" />
              <span class="hidden-mobile">{{ t('character_manager.delete') }}</span>
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- Editor Modal -->
    <teleport to="body">
      <div v-if="showEditor" class="modal-overlay" @click.self="showEditor = false">
        <div class="modal-content" @click.stop>
          <div class="modal-header">
            <h3 class="modal-title">{{ editingChar ? t('character_manager.edit_character') : t('character_manager.add_character') }}</h3>
            <button class="btn btn-ghost" @click="showEditor = false" aria-label="Close">
              <Icon icon="mdi:close" width="20" height="20" />
            </button>
          </div>
          <div class="modal-body p-4">
            <div class="form-group mb-4">
              <label class="form-label">{{ t('character_manager.character_name') }}</label>
              <input v-model="formName" type="text" class="form-control" :placeholder="t('character_manager.enter_character_name')" autofocus />
            </div>
            <div class="form-group mb-4">
              <label class="form-label">{{ t('character_manager.voice_id') }}</label>
              <input v-model="formVoice" type="text" class="form-control" :placeholder="t('character_manager.optional_voice_id')" />
            </div>
            <div class="form-group mb-4">
              <label class="form-label">{{ t('character_manager.emotion') }}</label>
              <select v-model="formEmotion" class="form-control">
                <option value="neutral">{{ t('character_manager.emotion_neutral') }}</option>
                <option value="happy">{{ t('character_manager.emotion_happy') }}</option>
                <option value="sad">{{ t('character_manager.emotion_sad') }}</option>
                <option value="angry">{{ t('character_manager.emotion_angry') }}</option>
                <option value="fearful">{{ t('character_manager.emotion_fearful') }}</option>
                <option value="surprised">{{ t('character_manager.emotion_surprised') }}</option>
              </select>
            </div>
            <div class="grid grid-auto-fill gap-4">
              <div>
                <label class="form-label">{{ t('character_manager.pitch') }}</label>
                <input v-model.number="formPitch" type="number" step="1" min="-12" max="12" class="form-control" />
              </div>
              <div>
                <label class="form-label">{{ t('character_manager.speed') }}</label>
                <input v-model.number="formSpeed" type="number" step="0.1" min="0.5" max="2.0" class="form-control" />
              </div>
            </div>
          </div>
          <div class="modal-footer flex justify-end gap-2 p-4 border-t" style="border-color: var(--color-border);">
            <button class="btn btn-outline" @click="showEditor = false">{{ t('common.cancel') }}</button>
            <button class="btn btn-primary" @click="saveCharacter">{{ t('common.save') }}</button>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<style scoped>
.character-manager {
  max-width: 960px;
}

.character-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.character-avatar {
  flex-shrink: 0;
}

.character-voice {
  display: flex;
  align-items: center;
}

.character-voice .inline {
  display: inline-flex;
}

.character-actions {
  flex-shrink: 0;
}

.character-list {
  margin-top: 8px;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 1000;
  animation: fadeIn var(--transition) ease-out;
}

.modal-content {
  background: var(--color-card-bg);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  width: 100%;
  max-width: 480px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  animation: slideUp var(--transition) ease-out;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
}

.modal-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text);
}

.modal-body {
  flex: 1;
  overflow-y: auto;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--color-border);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Responsive */
@media (max-width: 767px) {
  .modal-content {
    margin: 12px;
    max-height: calc(100vh - 24px);
  }
  .character-actions .hidden-mobile {
    display: none;
  }
}
</style>