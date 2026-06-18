<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as api from '../api'
import type { Character } from '../types'
import { Icon } from '@iconify/vue'

const route = useRoute()
const router = useRouter()
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

const emotionOptions = ['neutral', 'happy', 'sad', 'angry', 'surprised', 'whisper']

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
  formName.value = c.name || ''
  formVoice.value = (c as any).suggested_voice_id || ''
  formEmotion.value = (c as any).default_emotion || 'neutral'
  formPitch.value = (c as any).pitch_shift || 0
  formSpeed.value = (c as any).speech_rate || 1.0
  editingChar.value = c
  showEditor.value = true
}

async function saveCharacter() {
  if (!formName.value.trim()) return
  const payload = {
    name: formName.value.trim(),
    suggested_voice_id: formVoice.value || undefined,
    default_emotion: formEmotion.value,
    pitch_shift: formPitch.value,
    speech_rate: formSpeed.value,
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
    alert('保存失败: ' + (e.message || e))
  }
}

async function removeCharacter(id: number) {
  if (!confirm('确定移除该角色？')) return
  try {
    await api.deleteCharacter(projectId, id)
    characters.value = characters.value.filter((c) => c.id !== id)
  } catch (e: any) {
    alert('删除失败: ' + (e.message || e))
  }
}

function getVoicePreviewUrl(voicePreset?: string): string {
  if (!voicePreset) return ''
  return `/api/voices/${voicePreset}/preview`
}
</script>