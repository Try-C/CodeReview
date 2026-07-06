import { createRouter, createWebHistory } from 'vue-router'
import { clearAuth, isTokenExpired } from '@/api/client'

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
      meta: { requiresAuth: true },
      component: () => import('@/views/TaskProgressView.vue'),
    },
    {
      path: '/tasks/:taskId/report',
      name: 'report',
      meta: { requiresAuth: true },
      component: () => import('@/views/ReportDetailView.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
    },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to, _from, next) => {
  if (to.meta.requiresAuth) {
    const token = localStorage.getItem('access_token')
    if (!token || isTokenExpired()) {
      clearAuth()
      next({ name: 'home', query: { needLogin: '1' } })
      return
    }
  }
  next()
})

export default router
