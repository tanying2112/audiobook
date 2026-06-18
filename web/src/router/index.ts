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
  ],
})

export default router
