<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import * as api from '../api'
import type { Character } from '../types'
import { useI18n } from '../i18n'

const route = useRoute()
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

onMounted(async () => {
  loading.value = true
  try {
    characters.value = await api.fetchCharacters(projectId)
  } finally {
    loading.value = false
  }
})

async function addCharacter() {
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
    if (editingChar.value) {
      const updated = await api.updateCharacter(projectId, editingChar.value.id!, payload)
      const idx = characters.value.findIndex((c) => c.id === updated.id)
      if (idx !== -1) characters.value[idx] = updated
    } else {
      const created = await api.createCharacter(projectId, payload)
      characters.value.push(created)
    }
    showEditor.value = false
  } catch (e: any) {
    alert(t('character_manager.save_failed') + (e.message || e))
  }
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
</script>

<template>
  <div class="character-manager">
    <div class="page-header">
      <h1>{{ t('character_manager.title') }}</h1>
      <button class="btn btn-primary" @click="addCharacter">{{ t('character_manager.add_character') }}</button>
    </div>

    <div v-if="loading" class="loading">{{ t('character_manager.loading') }}</div>

    <div v-else class="character-list">
      <div v-for="c in characters" :key="c.id" class="character-card">
        <div class="character-name">{{ c.canonical_name }}</div>
        <div class="character-actions">
          <button class="btn btn-sm" @click="editCharacter(c)">{{ t('character_manager.edit') }}</button>
          <button class="btn btn-sm btn-danger" @click="removeCharacter(c.id!)">{{ t('character_manager.delete') }}</button>
        </div>
      </div>
    </div>

    <div v-if="showEditor" class="modal-overlay" @click.self="showEditor = false">
      <div class="modal">
        <h2>{{ editingChar ? t('character_manager.edit_character') : t('character_manager.add_character') }}</h2>
        <div class="form-group">
          <label>{{ t('character_manager.character_name') }}</label>
          <input v-model="formName" type="text" class="form-control" :placeholder="t('character_manager.enter_character_name')" />
        </div>
        <div class="form-group">
          <label>{{ t('character_manager.voice_id') }}</label>
          <input v-model="formVoice" type="text" class="form-control" :placeholder="t('character_manager.optional_voice_id')" />
        </div>
        <div class="modal-actions">
          <button class="btn" @click="saveCharacter">{{ t('common.save') }}</button>
          <button class="btn btn-ghost" @click="showEditor = false">{{ t('common.cancel') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.character-manager { max-width: 800px; margin: 0 auto; padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h1 { margin: 0; font-size: 22px; }
.character-list { display: flex; flex-direction: column; gap: 12px; }
.character-card { display: flex; justify-content: space-between; align-items: center; padding: 16px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; }
.character-name { font-weight: 600; font-size: 16px; }
.character-actions { display: flex; gap: 8px; }
.btn-sm { padding: 6px 12px; font-size: 13px; }
.btn-danger { background: #fee2e2; color: #dc2626; }
.btn-danger:hover { background: #fecaca; }
.loading { text-align: center; padding: 60px; color: #64748b; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; padding: 24px; border-radius: 12px; width: 100%; max-width: 400px; }
.modal h2 { margin: 0 0 20px; font-size: 18px; }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; margin-bottom: 6px; font-size: 14px; font-weight: 500; }
.form-control { width: 100%; padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }
</style>
