import { createRouter, createWebHistory } from 'vue-router'

import { isAuthenticated } from '../api'
import Login from '../pages/Login.vue'
import Register from '../pages/Register.vue'
import Dashboard from '../pages/Dashboard.vue'
import Incomes from '../pages/Incomes.vue'
import Plans from '../pages/Plans.vue'
import PlanMovements from '../pages/PlanMovements.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: () => (isAuthenticated() ? '/dashboard' : '/login') },
    { path: '/login', component: Login, meta: { public: true } },
    { path: '/register', component: Register, meta: { public: true } },
    { path: '/dashboard', component: Dashboard },
    { path: '/incomes', component: Incomes },
    { path: '/plans', component: Plans },
    { path: '/plans/:id/movements', component: PlanMovements },
  ],
})

router.beforeEach((to) => {
  if (!to.meta.public && !isAuthenticated()) return '/login'
  return true
})

export default router
