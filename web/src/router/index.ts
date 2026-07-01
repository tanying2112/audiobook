import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'projects',
      component: () => import('../views/Projects.vue'),
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
      // ⚠️ 临时验证路由，SSE/内联小窗验证通过后删除（含 SseDemo.vue）
      path: '/sse-demo',
      name: 'sse-demo',
      component: () => import('../views/SseDemo.vue'),
    },
  ],
})

export default router
