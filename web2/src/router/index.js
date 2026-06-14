import { createRouter, createWebHistory } from 'vue-router'
import { isAuthenticated } from '../api'

import Login from '../pages/Login.vue'
import Hoy from '../pages/Hoy.vue'
import Finanzas from '../pages/Finanzas.vue'
import Plan from '../pages/Plan.vue'
import Perfil from '../pages/Perfil.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: () => (isAuthenticated() ? '/hoy' : '/login') },
    { path: '/login', component: Login, meta: { public: true } },
    { path: '/hoy', component: Hoy },
    { path: '/finanzas', component: Finanzas },
    { path: '/plan', component: Plan },
    { path: '/perfil', component: Perfil },
    { path: '/:catchAll(.*)', redirect: '/' },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to) => {
  if (!to.meta.public && !isAuthenticated()) return '/login'
  if (to.path === '/login' && isAuthenticated()) return '/hoy'
  return true
})

export default router
