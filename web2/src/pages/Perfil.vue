<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { api, getUser, clearSession } from '../api'
import { formatMoney } from '../format'

const router = useRouter()
const user = getUser()
const plan = ref(null)
const error = ref('')

onMounted(async () => {
  try {
    const plans = await api.listPlans()
    plan.value = plans[0] ?? null
  } catch (e) {
    error.value = e.message
  }
})

const initial = computed(() => (user?.display_name?.trim()?.[0] ?? 'M').toUpperCase())

function logout() {
  clearSession()
  router.push('/login')
}
</script>

<template>
  <AppShell title="Perfil">
    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="card" style="display: flex; align-items: center; gap: 14px">
      <span
        class="ava"
        style="width: 52px; height: 52px; font-size: 22px; font-weight: 800; color: var(--indigo)"
      >{{ initial }}</span>
      <div class="grow">
        <div class="title" style="font-size: 17px">{{ user?.display_name || 'Tu cuenta' }}</div>
        <div class="meta">Margin · prototipo</div>
      </div>
    </div>

    <div class="section-title">Mi plan activo</div>
    <div v-if="plan" class="card">
      <div class="stat" style="padding-top: 0">
        <span class="k">Plan</span>
        <span class="v">{{ plan.name }}</span>
      </div>
      <div class="stat">
        <span class="k">Gasto mensual</span>
        <span class="v">{{ formatMoney(plan.dial_amount, plan.dial_currency_id) }}</span>
      </div>
      <div class="stat" v-if="plan.goal_amount">
        <span class="k">Objetivo de ahorro</span>
        <span class="v">{{ formatMoney(plan.goal_amount, plan.goal_currency_id) }}</span>
      </div>
      <button class="btn btn-ghost" style="margin-top: 12px" @click="router.push('/plan')">
        Ver mi plan
      </button>
    </div>
    <div v-else class="muted">Todavía no creaste un plan.</div>

    <div class="section-title">Cuenta</div>
    <button class="btn btn-ghost" @click="logout">Cerrar sesión</button>

    <p class="muted" style="text-align: center; margin-top: 24px; font-size: 12px">
      Margin web2 · prototipo del producto
    </p>
  </AppShell>
</template>
