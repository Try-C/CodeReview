import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '@/views/HomeView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/tasks/:taskId/progress',
      name: 'task-progress',
      component: () => import('@/views/TaskProgressView.vue'),
    },
    {
      path: '/tasks/:taskId/report',
      name: 'report',
      component: () => import('@/views/ReportDetailView.vue'),
    },
  ],
})

export default router
