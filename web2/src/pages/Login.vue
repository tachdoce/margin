<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, saveSession, ensureBootstrap } from '../api'

const router = useRouter()
const mode = ref('login') // 'login' | 'register'
const email = ref('')
const password = ref('')
const displayName = ref('')
const error = ref('')
const loading = ref(false)

function toggle() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
}

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const res =
      mode.value === 'login'
        ? await api.login(email.value, password.value)
        : await api.register(email.value, password.value, displayName.value || null)
    saveSession(res)
    await ensureBootstrap({ force: true })
    router.push('/hoy')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth">
    <div class="brand"><span class="dot">M</span> Margin</div>
    <h1 style="font-size: 26px; margin-bottom: 6px">
      {{ mode === 'login' ? 'Hola de nuevo' : 'Creá tu cuenta' }}
    </h1>
    <p class="muted" style="margin-bottom: 22px">
      {{ mode === 'login' ? 'Entrá para ver tu plan.' : 'Empezá a ordenar tus pagos.' }}
    </p>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <form @submit.prevent="submit">
      <div v-if="mode === 'register'" class="field">
        <label>Tu nombre</label>
        <input v-model="displayName" type="text" placeholder="Cómo te llamás" />
      </div>
      <div class="field">
        <label>Email</label>
        <input v-model="email" type="email" autocomplete="email" placeholder="vos@email.com" />
      </div>
      <div class="field">
        <label>Contraseña</label>
        <input v-model="password" type="password" autocomplete="current-password" placeholder="••••••••" />
      </div>
      <button class="btn btn-primary" type="submit" :disabled="loading">
        {{ loading ? 'Entrando…' : mode === 'login' ? 'Entrar' : 'Crear cuenta' }}
      </button>
    </form>

    <p class="muted" style="text-align: center; margin-top: 18px">
      {{ mode === 'login' ? '¿No tenés cuenta?' : '¿Ya tenés cuenta?' }}
      <a style="color: var(--indigo); font-weight: 600" @click="toggle">
        {{ mode === 'login' ? 'Registrate' : 'Entrá' }}
      </a>
    </p>
  </div>
</template>
