<script setup>
import { onMounted, ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import { getUser, getBootstrap, ensureBootstrap } from '../api'

const user = getUser()

const bootstrap = ref(getBootstrap())
const error = ref('')
const loading = ref(false)
const open = ref({}) // catálogo -> expandido?

async function load({ force = false } = {}) {
  error.value = ''
  loading.value = true
  try {
    bootstrap.value = await ensureBootstrap({ force })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (!bootstrap.value) load() // fallback: cache vacía (ej. sesión vieja)
})

function toggle(name) {
  open.value[name] = !open.value[name]
}

function itemLabel(item) {
  if (item && typeof item === 'object') {
    const id = item.id ?? item.level ?? item.code
    const name = item.name ?? item.message
    if (id != null && name != null) return `${id} · ${name}`
  }
  return JSON.stringify(item)
}
</script>

<template>
  <div class="screen">
    <AppNav />
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

      <div class="field">
        <div class="row">
          <label>Bootstrap <span class="muted" v-if="bootstrap">v{{ bootstrap.version }}</span></label>
          <button class="ghost" :disabled="loading" @click="load({ force: true })">
            {{ loading ? 'Cargando…' : 'Refrescar' }}
          </button>
        </div>
        <p v-if="error" class="error">{{ error }}</p>
        <ul v-if="bootstrap" class="catalogs">
          <li v-for="(items, name) in bootstrap.catalogs" :key="name">
            <button class="catalog-head" @click="toggle(name)">
              <span>{{ open[name] ? '▾' : '▸' }} {{ name }}</span>
              <span class="muted">{{ items.length }}</span>
            </button>
            <ul v-if="open[name]" class="catalog-items">
              <li v-for="(item, i) in items" :key="i" class="muted">{{ itemLabel(item) }}</li>
            </ul>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
