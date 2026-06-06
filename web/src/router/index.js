import { createRouter, createWebHistory } from 'vue-router'

import { isAuthenticated } from '../api'
import Login from '../pages/Login.vue'
import Register from '../pages/Register.vue'
import Dashboard from '../pages/Dashboard.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: () => (isAuthenticated() ? '/dashboard' : '/login') },
    { path: '/login', component: Login, meta: { public: true } },
    { path: '/register', component: Register, meta: { public: true } },
    { path: '/dashboard', component: Dashboard },
  ],
})

router.beforeEach((to) => {
  if (!to.meta.public && !isAuthenticated()) return '/login'
  return true
})

export default router
