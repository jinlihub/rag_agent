import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
    },
    {
      path: '/admin/qa-list',
      name: 'admin-qa-list',
      component: () => import('@/views/admin/QaListView.vue'),
      meta: { requiresAdmin: true },
    },
    {
      path: '/admin/system',
      name: 'admin-system',
      component: () => import('@/views/admin/SystemMonitorView.vue'),
      meta: { requiresAdmin: true },
    },
    { path: '/', redirect: '/chat' },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) return { path: '/chat' }
  if (to.path === '/login' && auth.isLoggedIn) return { path: '/chat' }
})

export default router
