<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { api, getUser, ensureBootstrap } from '../api'
import { money0, monthName } from '../format'
import { defaultCurrencyId } from '../format'

const router = useRouter()
const user = getUser()
const loading = ref(true)
const error = ref('')
const plan = ref(null)
const timeline = ref(null)

const cur = defaultCurrencyId

const currentKey = (() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
})()

const months = computed(() => timeline.value?.months ?? [])
const currentMonth = computed(
  () => months.value.find((m) => m.month >= currentKey) ?? null,
)
const healthy = computed(() => timeline.value?.healthy_debt_month ?? null)
const goal = computed(() => timeline.value?.goal_reached_month ?? null)

// Estado de la pantalla: qué mensaje y qué próximo paso mostrar.
const stage = computed(() => {
  if (!plan.value) return 'no-plan'
  if (!months.value.length) return 'no-data'
  if (healthy.value) return 'healthy'
  return 'organize'
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    await ensureBootstrap()
    const plans = await api.listPlans()
    plan.value = plans[0] ?? null
    if (plan.value) timeline.value = await api.getTimeline(plan.value.id)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(load)

const firstName = computed(() => {
  const n = user?.display_name?.trim()
  return n ? n.split(' ')[0] : 'Hola'
})
</script>

<template>
  <AppShell title="Hoy">
    <p v-if="error" class="error-banner">{{ error }}</p>

    <p class="card-lead" style="margin-bottom: 6px">Hola{{ user?.display_name ? ',' : '' }}</p>
    <h2 style="font-size: 24px; margin-bottom: 16px">{{ firstName }} 👋</h2>

    <div v-if="loading" class="muted">Cargando tu situación…</div>

    <template v-else>
      <!-- Hero de salud financiera -->
      <div class="hero">
        <template v-if="stage === 'healthy'">
          <div class="eyebrow">Tu salud financiera</div>
          <div class="big">Libre de deuda cara en {{ monthName(healthy) }}</div>
          <div class="sub" v-if="goal">🎯 Y llegás a tu objetivo en {{ monthName(goal) }}.</div>
          <div class="sub" v-else>Seguí el plan y vas a dejar de generar intereses.</div>
        </template>
        <template v-else-if="stage === 'organize'">
          <div class="eyebrow">Tu salud financiera</div>
          <div class="big">Organizá tus pagos</div>
          <div class="sub">Cuando organices, te decimos en qué mes salís de la deuda cara.</div>
        </template>
        <template v-else-if="stage === 'no-data'">
          <div class="eyebrow">Empecemos</div>
          <div class="big">Cargá tus ingresos y deudas</div>
          <div class="sub">Con eso armamos tu futuro mes a mes.</div>
        </template>
        <template v-else>
          <div class="eyebrow">Empecemos</div>
          <div class="big">Creá tu primer plan</div>
          <div class="sub">Un plan es tu estrategia para ordenar los pagos.</div>
        </template>
      </div>

      <!-- Resumen del mes -->
      <div v-if="currentMonth" class="card">
        <div class="card-lead" style="margin-bottom: 8px">Este mes · {{ monthName(currentMonth.month) }}</div>
        <div class="stat">
          <span class="k">Disponible</span>
          <span class="v">{{ money0(currentMonth.available, cur()) }}</span>
        </div>
        <div class="stat">
          <span class="k">A cobrar</span>
          <span class="v pos">{{ money0(currentMonth.pending_income, cur()) }}</span>
        </div>
        <div class="stat">
          <span class="k">A pagar</span>
          <span class="v neg">{{ money0(currentMonth.pending_expenses, cur()) }}</span>
        </div>
        <div class="stat" style="border-top: 1px solid var(--line); margin-top: 6px; padding-top: 10px">
          <span class="k" style="font-weight: 700; color: var(--ink)">Te queda</span>
          <span class="v" :class="Number(currentMonth.balance) < 0 ? 'neg' : 'pos'">
            {{ money0(currentMonth.balance, cur()) }}
          </span>
        </div>
        <div v-if="Number(currentMonth.generated_interest) > 0" style="margin-top: 10px">
          <span class="badge red">Este mes generás {{ money0(currentMonth.generated_interest, cur()) }} de interés</span>
        </div>
      </div>

      <!-- Próximo paso -->
      <button
        v-if="stage === 'no-plan'"
        class="btn btn-primary"
        @click="router.push('/plan')"
      >
        Crear mi plan
      </button>
      <button
        v-else-if="stage === 'no-data'"
        class="btn btn-primary"
        @click="router.push('/finanzas')"
      >
        Cargar ingresos y deudas
      </button>
      <button
        v-else-if="stage === 'organize'"
        class="btn btn-primary"
        @click="router.push('/plan')"
      >
        Organizar mis pagos
      </button>
      <button v-else class="btn btn-ghost" @click="router.push('/plan')">
        Ver mi plan completo
      </button>
    </template>
  </AppShell>
</template>
