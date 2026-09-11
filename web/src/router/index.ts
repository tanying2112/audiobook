import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('../views/RegisterView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      name: 'projects',
      component: () => import('../views/Projects.vue'),
    },
    {
      path: '/projects',
      name: 'project-management',
      component: () => import('../views/ProjectManagement.vue'),
    },
    {
      path: '/projects/:id',
      name: 'project-detail',
      component: () => import('../views/ProjectDetail.vue'),
    },
    {
      path: '/projects/:projectId/chapters/:chapterId',
      name: 'chapter-timeline',
      component: () => import('../views/ChapterTimeline.vue'),
    },
    {
      path: '/projects/:projectId/characters',
      name: 'character-manager',
      component: () => import('../views/CharacterManager.vue'),
    },
    {
      path: '/projects/:projectId/quality',
      name: 'quality-report',
      component: () => import('../views/QualityReport.vue'),
    },
    {
      path: '/feedback',
      name: 'feedback-editor',
      component: () => import('../views/FeedbackEditor.vue'),
    },
    {
      path: '/harness',
      name: 'harness-dashboard',
      component: () => import('../views/HarnessDashboard.vue'),
    },
    {
      path: '/projects/:id/upload',
      name: 'upload',
      component: () => import('../views/UploadView.vue'),
    },
    {
      path: '/projects/:id/export',
      name: 'export',
      component: () => import('../views/ExportView.vue'),
    },
    {
      path: '/projects/:id/publish',
      name: 'publish',
      component: () => import('../views/PublishView.vue'),
    },
    {
      path: '/projects/:projectId/translation',
      name: 'translation',
      component: () => import('../views/TranslationView.vue'),
    },
    {
      path: '/projects/:projectId/voice-clone',
      name: 'voice-clone',
      component: () => import('../views/VoiceCloneView.vue'),
    },
    {
      path: '/projects/:projectId/auto-run',
      name: 'auto-run',
      component: () => import('../views/AutoRunView.vue'),
    },
    {
      path: '/projects/:projectId/runs',
      name: 'runs',
      component: () => import('../views/RunsView.vue'),
    },
    {
      path: '/projects/:projectId/knowledge',
      name: 'knowledge',
      component: () => import('../views/KnowledgeBaseView.vue'),
    },
    {
      path: '/monitoring',
      name: 'monitoring-dashboard',
      component: () => import('../views/MonitoringDashboard.vue'),
    },
    {
      path: '/providers',
      name: 'provider-manager',
      component: () => import('../views/ProviderManager.vue'),
    },
    {
      path: '/model-market',
      name: 'model-market',
      component: () => import('../views/ModelMarket.vue'),
    },
    {
      path: '/projects/:projectId/dashboard',
      name: 'project-dashboard',
      component: () => import('../views/DashboardView.vue'),
    },
    {
      path: '/projects/:projectId/agent-chat',
      name: 'agent-chat',
      component: () => import('../views/AgentChatView.vue'),
    },
    {
      path: '/projects/:projectId/video-canvas',
      name: 'video-canvas',
      component: () => import('../views/VideoCanvasView.vue'),
    },
    {
      path: '/projects/:id/overview',
      name: 'project-overview',
      component: () => import('../views/ProjectOverviewView.vue'),
    },
    {
      path: '/evolution/promotions',
      name: 'promotions',
      component: () => import('../views/PromotionsView.vue'),
    },
    {
      path: '/evolution/golden',
      name: 'golden-data',
      component: () => import('../views/GoldenDataView.vue'),
    },
    {
      path: '/evolution/sop',
      name: 'sop-rules',
      component: () => import('../views/SopRulesView.vue'),
    },
    {
      path: '/evolution/feedback',
      name: 'feedback-insights',
      component: () => import('../views/FeedbackInsightsView.vue'),
    },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('../views/AdminView.vue'),
      meta: { requiresSuperuser: true },
    },
    {
      path: '/projects/:id/audio-segments',
      name: 'audio-segments',
      component: () => import('../views/AudioSegmentEditor.vue'),
    },
    {
      path: '/waveform-demo',
      name: 'waveform-demo',
      component: () => import('../views/WaveformDemoView.vue'),
    },
  ],
})

router.beforeEach(async (to, _from) => {
  const authStore = useAuthStore()
  const isPublic = to.matched.some((record) => record.meta.public)

  if (!isPublic && !authStore.isAuthenticated()) {
    return '/login'
  } else if (to.path === '/login' && authStore.isAuthenticated()) {
    return '/'
  }
  if (to.meta.requiresSuperuser && authStore.isAuthenticated()) {
    if (!authStore.user) {
      try {
        await authStore.fetchUser()
      } catch {
        return '/login'
      }
    }
    if (!authStore.user?.is_superuser) {
      return '/'
    }
  }
  // Return undefined to continue navigation
})

export default router
