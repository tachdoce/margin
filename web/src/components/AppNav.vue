<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { clearSession } from '../api'

const router = useRouter()
const open = ref(false)

function logout() {
  open.value = false
  clearSession()
  router.push('/login')
}
</script>

<template>
  <header class="navbar">
    <button class="hamburger" aria-label="Abrir menú" @click="open = true">☰</button>
    <span class="navbar-title">Margin</span>
  </header>

  <div v-if="open" class="drawer-overlay" @click="open = false"></div>
  <nav class="drawer" :class="{ 'drawer-open': open }">
    <router-link class="drawer-item" to="/dashboard" @click="open = false">Dashboard</router-link>
    <router-link class="drawer-item" to="/incomes" @click="open = false">Ingresos</router-link>
    <button class="drawer-logout" @click="logout">Cerrar sesión</button>
  </nav>
</template>
