<script setup>
import { useRouter } from 'vue-router'
import { getUser, clearSession } from '../api'

const router = useRouter()
const user = getUser()

function logout() {
  clearSession()
  router.push('/login')
}
</script>

<template>
  <div class="screen">
    <div class="content">
      <h1>Dashboard</h1>
      <div class="field">
        <label>ID</label>
        <p class="muted">{{ user?.id }}</p>
      </div>
      <div class="field">
        <label>País</label>
        <p class="muted">{{ user?.country_code }}</p>
      </div>
      <div class="field">
        <label>Nombre</label>
        <p class="muted">{{ user?.display_name || '—' }}</p>
      </div>
      <button class="ghost" @click="logout">Cerrar sesión</button>
    </div>
  </div>
</template>
