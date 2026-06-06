<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, saveSession, ensureBootstrap } from '../api'

const router = useRouter()
const email = ref('')
const password = ref('')
const displayName = ref('')
const error = ref('')

async function submit() {
  error.value = ''
  try {
    const data = await api.register(email.value, password.value, displayName.value)
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
      <h1>Crear cuenta</h1>
      <form class="content" style="padding: 0" @submit.prevent="submit">
        <div class="field">
          <label>Email</label>
          <input v-model="email" type="email" autocomplete="email" />
        </div>
        <div class="field">
          <label>Contraseña</label>
          <input v-model="password" type="password" autocomplete="new-password" />
        </div>
        <div class="field">
          <label>Nombre (opcional)</label>
          <input v-model="displayName" type="text" autocomplete="name" />
        </div>
        <p v-if="error" class="error">{{ error }}</p>
        <button class="primary" type="submit">Registrarme</button>
      </form>
      <p class="muted">¿Ya tenés cuenta? <router-link to="/login">Ingresá</router-link></p>
    </div>
  </div>
</template>
