<template>
  <div class="review-gate-view">
    <!-- 页头 -->
    <header class="view-header">
      <div>
        <h1 class="view-title">
          <Icon icon="mdi:clipboard-check-search-outline" width="24" height="24" />
          {{ t('review_gate.title') }}
        </h1>
        <p class="text-secondary view-subtitle">{{ t('review_gate.subtitle') }}</p>
      </div>
      <button
        v-if="!allApproved"
        class="btn btn-primary"
        :disabled="loading"
        @click="handleApproveAll"
      >
        <Icon icon="mdi:check-all" width="16" height="16" />
        {{ t('review_gate.approve_all') }}
      </button>
    </header>

    <!-- 终审门状态横幅 -->
    <div
      class="gate-banner"
      :class="isGateActive ? 'gate-banner--active' : 'gate-banner--idle'"
    >
      <Icon
        :icon="isGateActive ? 'mdi:gate-arrow-right' : 'mdi:gate'"
        width="18"
        height="18"
      />
      <span>{{ isGateActive ? t('review_gate.gate_active') : t('review_gate.gate_inactive') }}</span>
      <span class="gate-banner__progress">
        {{ summary?.approved_chapters ?? 0 }} / {{ summary?.total_chapters ?? 0 }}
      </span>
      <span class="badge">{{ summary?.run_status || 'not_started' }}</span>
    </div>

    <!-- 提示条 -->
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="lastSaveMessage" class="alert alert-success">{{ lastSaveMessage }}</div>

    <!-- 三栏工作台 -->
    <div v-if="loading" class="loading-box">
      <Icon icon="mdi:loading" width="24" height="24" class="spinner" />
    </div>
    <div v-else class="workbench">
      <aside class="workbench__chapters">
        <h2 class="panel-title">{{ t('review_gate.chapter_list') }}</h2>
        <ReviewChapterList
          :chapters="chapters"
          :selected-chapter-id="selectedChapterId"
          @select="selectChapter"
          @approve="handleApprove"
          @reset="handleReset"
        />
      </aside>

      <section class="workbench__paragraphs">
        <div class="panel-title-row">
          <h2 class="panel-title">{{ t('review_gate.paragraph_list') }}</h2>
          <span v-if="routingPreview" class="badge badge-secondary">
            {{ t('review_gate.preview_count', {
              synth: routingPreview.synthesized_count,
              skip: routingPreview.skipped_count,
            }) }}
          </span>
        </div>
        <div v-if="paragraphsLoading" class="loading-box">
          <Icon icon="mdi:loading" width="20" height="20" class="spinner" />
        </div>
        <ReviewParagraphList
          v-else
          :paragraphs="paragraphs"
          :previews="previewByParagraphId"
          :selected-paragraph-id="selectedParagraphId"
          @select="selectParagraph"
        />
      </section>

      <section class="workbench__edit">
        <h2 class="panel-title">{{ t('review_gate.edit_panel') }}</h2>
        <ReviewEditPanel
          :paragraph="selectedParagraph"
          :tts-voices="ttsVoices"
          :saving="saving"
          @save="saveParagraphEdit"
        />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '../i18n'
import { Icon } from '@iconify/vue'
import { useReviewGate } from '../composables/useReviewGate'
import ReviewChapterList from '../components/review/ReviewChapterList.vue'
import ReviewParagraphList from '../components/review/ReviewParagraphList.vue'
import ReviewEditPanel from '../components/review/ReviewEditPanel.vue'

const { t } = useI18n()

const {
  loading,
  summary,
  chapters,
  isGateActive,
  selectedChapterId,
  selectChapter,
  paragraphs,
  paragraphsLoading,
  routingPreview,
  previewByParagraphId,
  selectedParagraphId,
  selectedParagraph,
  saving,
  error,
  lastSaveMessage,
  ttsVoices,
  handleApprove,
  handleReset,
  handleApproveAll,
  saveParagraphEdit,
} = useReviewGate()

const allApproved = computed(() => summary.value?.all_approved ?? false)

function selectParagraph(paragraphId: number): void {
  selectedParagraphId.value = paragraphId
}
</script>

<style scoped>
.review-gate-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.view-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.view-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.5rem;
  margin: 0;
}

.view-subtitle {
  margin: 0.25rem 0 0;
}

.gate-banner {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.9rem;
  border-radius: 8px;
  font-size: 0.9rem;
}

.gate-banner--active {
  background: rgba(255, 159, 10, 0.1);
  border: 1px solid rgba(255, 159, 10, 0.4);
  color: inherit;
}

.gate-banner--idle {
  background: rgba(128, 128, 128, 0.08);
  border: 1px solid var(--color-border);
}

.gate-banner__progress {
  margin-left: auto;
  font-weight: 600;
}

.workbench {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(300px, 1.2fr) minmax(320px, 1fr);
  gap: 1rem;
  align-items: start;
}

.workbench__chapters,
.workbench__paragraphs,
.workbench__edit {
  padding: 0.9rem;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-height: 320px;
  max-height: 75vh;
  overflow-y: auto;
}

.panel-title {
  font-size: 1rem;
  margin: 0;
}

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.loading-box {
  display: flex;
  justify-content: center;
  padding: 2rem 0;
}

.alert {
  padding: 0.6rem 0.9rem;
  border-radius: 8px;
  font-size: 0.9rem;
}

.alert-error {
  background: rgba(220, 53, 69, 0.12);
  border: 1px solid rgba(220, 53, 69, 0.4);
}

.alert-success {
  background: rgba(34, 160, 107, 0.12);
  border: 1px solid rgba(34, 160, 107, 0.4);
}

/* 窄屏：三栏纵向堆叠 */
@media (max-width: 900px) {
  .workbench {
    grid-template-columns: 1fr;
  }

  .workbench__chapters,
  .workbench__paragraphs,
  .workbench__edit {
    max-height: none;
  }
}
</style>
