<template>
  <div class="upload-action-bar">
    <div class="action-group primary-actions">
      <el-button
        v-if="canStartPipeline"
        type="primary"
        size="large"
        :loading="startPipelineLoading"
        @click="handleStartPipeline"
        class="start-btn"
      >
        <VideoPlay /><span>{{ t('upload.start_pipeline') }}</span>
      </el-button>
      <el-button
        v-else-if="extractionResult"
        type="primary"
        size="large"
        :disabled="true"
      >
        <Lock /><span>{{ t('upload.select_chapters_first') }}</span>
      </el-button>
    </div>

    <div class="action-group secondary-actions">
      <el-button
        type="default"
        size="default"
        @click="handleBackToEdit"
      >
        <ArrowLeft /><span>{{ t('upload.back_to_edit') }}</span>
      </el-button>
      <el-button
        type="default"
        size="default"
        @click="handleSaveDraft"
      >
        <Edit /><span>{{ t('upload.save_draft') }}</span>
      </el-button>
    </div>

    <div class="action-group status-info" v-if="extractionLoading">
      <el-tag type="info" effect="plain">
        <Loading class="spin" />{{ t('upload.loading_extraction') }}
      </el-tag>
    </div>
    <div class="action-group status-info" v-else-if="extractionResult">
      <el-tag type="success" effect="plain">
        <CircleCheck />{{ t('upload.extraction_ready') }}
      </el-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '@/i18n'
import { ElButton, ElTag } from 'element-plus'
import {
  VideoPlay, Lock, ArrowLeft, Edit, Loading, CircleCheck
} from '@element-plus/icons-vue'

const props = defineProps<{
  extractionResult: {
    total_chapters: number
  } | null
  selectedChapterIds: number[]
  startPipelineLoading: boolean
  extractionLoading: boolean
  canStartPipeline: boolean
}>()

const emit = defineEmits<{
  'start-pipeline': []
  'back-to-edit': []
  'save-draft': []
}>()

const { t } = useI18n()

const handleStartPipeline = () => {
  emit('start-pipeline')
}

const handleBackToEdit = () => {
  emit('back-to-edit')
}

const handleSaveDraft = () => {
  emit('save-draft')
}
</script>

<style scoped>
.upload-action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-secondary, #fafafa);
  border-top: 1px solid var(--border-color, #e8e8e8);
  border-radius: 0 0 8px 8px;
}

.action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.primary-actions {
  flex: 1;
  justify-content: flex-end;
}

.start-btn {
  min-width: 160px;
  height: 44px;
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.secondary-actions {
  display: flex;
  gap: 8px;
}

.status-info {
  display: flex;
  align-items: center;
}

.status-info .el-tag {
  font-size: 13px;
  height: 28px;
}

.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .upload-action-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .primary-actions {
    justify-content: stretch;
  }
  .secondary-actions {
    justify-content: center;
  }
  .status-info {
    justify-content: center;
  }
}
</style>