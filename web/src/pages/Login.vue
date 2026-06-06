<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, saveSession, ensureBootstrap } from '../api'

const router = useRouter()
const email = ref('')
const password = ref('')
const error = ref('')

async function submit() {
  error.value = ''
  try {
    const data = await api.login(email.value, password.value)
    saveSession(data)
    await ensureBootstrap()
    router.push('/dashboard')
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <div class="content">
      <h1>Ingresar</h1>
      <form class="content" style="padding: 0" @submit.prevent="submit">
        <div class="field">
          <label>Email</label>
          <input v-model="email" type="email" autocomplete="email" />
        </div>
        <div class="field">
          <label>Contraseña</label>
          <input v-model="password" type="password" autocomplete="current-password" />
        </div>
        <p v-if="error" class="error">{{ error }}</p>
        <button class="primary" type="submit">Ingresar</button>
      </form>
      <p class="muted">¿No tenés cuenta? <router-link to="/register">Registrate</router-link></p>
    </div>
  </div>
</template>
