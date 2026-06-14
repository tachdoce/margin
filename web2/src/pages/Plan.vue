<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import Sheet from '../components/Sheet.vue'
import { api, ensureBootstrap } from '../api'
import { formatMoney, money0, monthName, monthShort, defaultCurrencyId } from '../format'

const router = useRouter()
const plans = ref([])
const active = ref(null)
const timeline = ref(null)
const loading = ref(true)
const organizing = ref(false)
const error = ref('')
const toast = ref('')

const createOpen = ref(false)
const switchOpen = ref(false)
const saving = ref(false)
const newPlan = reactive({ name: '', dial_amount: '', goal_amount: '' })

const cur = defaultCurrencyId

const currentKey = (() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
})()

const months = computed(() => (timeline.value?.months ?? []).filter((m) => m.month >= currentKey))
const healthy = computed(() => timeline.value?.healthy_debt_month ?? null)
const goal = computed(() => timeline.value?.goal_reached_month ?? null)
const openDebts = computed(() => timeline.value?.open_debts ?? [])
const maxInterest = computed(() =>
  Math.max(1, ...months.value.map((m) => Number(m.generated_interest) || 0)),
)

function flash(msg) {
  toast.value = msg
  setTimeout(() => (toast.value = ''), 2200)
}

async function loadTimeline() {
  if (!active.value) return
  timeline.value = await api.getTimeline(active.value.id)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    await ensureBootstrap()
    plans.value = await api.listPlans()
    active.value = plans.value[0] ?? null
    await loadTimeline()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function organize() {
  if (!active.value || organizing.value) return
  organizing.value = true
  error.value = ''
  try {
    await api.runPlanning(active.value.id)
    await loadTimeline()
    flash('Pagos organizados ✓')
  } catch (e) {
    error.value = e.message
  } finally {
    organizing.value = false
  }
}

async function createPlan() {
  error.value = ''
  saving.value = true
  try {
    const body = { name: newPlan.name, dial_amount: String(newPlan.dial_amount), select_on_create: true }
    if (newPlan.goal_amount !== '') {
      body.goal_kind = 'ahorro_total'
      body.goal_amount = String(newPlan.goal_amount)
    }
    await api.createPlan(body)
    createOpen.value = false
    Object.assign(newPlan, { name: '', dial_amount: '', goal_amount: '' })
    flash('Plan creado ✓')
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function switchTo(p) {
  switchOpen.value = false
  if (p.id === active.value?.id) return
  try {
    await api.selectPlan(p.id)
    await load()
  } catch (e) {
    error.value = e.message
  }
}

function milestone(m) {
  if (m.month === goal.value) return { cls: 'indigo', txt: '🎯 objetivo' }
  if (m.month === healthy.value) return { cls: 'green', txt: '✓ deuda sana' }
  return null
}
function barWidth(m) {
  const v = Number(m.generated_interest) || 0
  return v <= 0 ? 0 : Math.max(6, Math.round((v / maxInterest.value) * 100))
}
</script>

<template>
  <AppShell title="Mi plan">
    <template #actions>
      <button v-if="active" class="btn btn-ghost btn-sm" @click="switchOpen = true">Cambiar</button>
    </template>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <div v-if="loading" class="muted">Cargando…</div>

    <!-- Sin planes -->
    <div v-else-if="!active" class="empty">
      <div class="ic">🗺️</div>
      <h3>Todavía no tenés un plan</h3>
      <p>Un plan es tu estrategia: cuánto gastás por mes y a qué objetivo apuntás.</p>
      <button class="btn btn-primary" style="max-width: 220px; margin: 0 auto" @click="createOpen = true">
        Crear mi plan
      </button>
    </div>

    <template v-else>
      <!-- Tarjeta del plan -->
      <div class="card">
        <div class="stat" style="padding-top: 0">
          <span class="k" style="font-weight: 700; color: var(--ink); font-size: 16px">{{ active.name }}</span>
          <span class="badge indigo">activo</span>
        </div>
        <div class="stat">
          <span class="k">Gasto mensual</span>
          <span class="v">{{ formatMoney(active.dial_amount, active.dial_currency_id) }}</span>
        </div>
        <div class="stat" v-if="active.goal_amount">
          <span class="k">Objetivo de ahorro</span>
          <span class="v">{{ formatMoney(active.goal_amount, active.goal_currency_id) }}</span>
        </div>
      </div>

      <!-- Hitos -->
      <div v-if="healthy || goal" class="card" style="display: flex; gap: 10px">
        <div style="flex: 1; text-align: center">
          <div class="card-lead">Deuda sana</div>
          <div style="font-weight: 800; color: var(--green); font-size: 16px; margin-top: 2px">
            {{ healthy ? monthName(healthy) : '—' }}
          </div>
        </div>
        <div style="width: 1px; background: var(--line)" />
        <div style="flex: 1; text-align: center">
          <div class="card-lead">Objetivo</div>
          <div style="font-weight: 800; color: var(--indigo); font-size: 16px; margin-top: 2px">
            {{ goal ? monthName(goal) : '—' }}
          </div>
        </div>
      </div>

      <button class="btn btn-primary" :disabled="organizing" @click="organize">
        {{ organizing ? 'Organizando…' : '✨ Organizar mis pagos' }}
      </button>

      <!-- Timeline -->
      <div class="section-title">Tu futuro mes a mes</div>
      <div v-if="!months.length" class="muted">Cargá ingresos y deudas para ver tu timeline.</div>
      <div v-else class="card">
        <div v-for="m in months" :key="m.month" class="tl-row">
          <span class="tl-month">{{ monthShort(m.month) }}</span>
          <span class="tl-bar">
            <i :style="{ width: barWidth(m) + '%', background: 'var(--red)' }" />
          </span>
          <span class="tl-right">
            <span v-if="milestone(m)" class="badge" :class="milestone(m).cls">{{ milestone(m).txt }}</span>
            <span v-else class="bal" :class="{ neg: Number(m.balance) < 0 }">{{ money0(m.balance, cur()) }}</span>
          </span>
        </div>
        <p class="muted" style="margin-top: 10px; font-size: 12px">
          La barra roja es el interés que generás ese mes. Baja a cero cuando salís de la deuda cara.
        </p>
      </div>

      <!-- Deuda abierta -->
      <template v-if="openDebts.length">
        <div class="section-title">Para pagar cuando puedas</div>
        <div v-for="e in openDebts" :key="e.id" class="item">
          <span class="ava">🤝</span>
          <div class="grow">
            <div class="title">{{ e.description }}</div>
            <div class="meta">sin fecha fija</div>
          </div>
          <span class="amount">{{ formatMoney(e.amount, e.currency_id) }}</span>
        </div>
      </template>
    </template>

    <!-- Crear plan -->
    <Sheet v-model="createOpen" title="Nuevo plan">
      <p v-if="error" class="error-banner">{{ error }}</p>
      <div class="field">
        <label>Nombre del plan</label>
        <input v-model="newPlan.name" type="text" placeholder="Salir de deudas" />
      </div>
      <div class="field">
        <label>¿Cuánto querés gastar por mes?</label>
        <input v-model="newPlan.dial_amount" type="text" inputmode="decimal" placeholder="30000" />
        <div class="hint">Tu gasto de vida (sin contar las deudas).</div>
      </div>
      <div class="field">
        <label>Objetivo de ahorro (opcional)</label>
        <input v-model="newPlan.goal_amount" type="text" inputmode="decimal" placeholder="100000" />
      </div>
      <button class="btn btn-primary" :disabled="saving" @click="createPlan">
        {{ saving ? 'Creando…' : 'Crear plan' }}
      </button>
    </Sheet>

    <!-- Cambiar plan -->
    <Sheet v-model="switchOpen" title="Cambiar de plan">
      <div v-for="p in plans" :key="p.id" class="item" style="cursor: pointer" @click="switchTo(p)">
        <span class="ava">🗺️</span>
        <div class="grow">
          <div class="title">{{ p.name }}</div>
          <div class="meta">gasto {{ formatMoney(p.dial_amount, p.dial_currency_id) }}</div>
        </div>
        <span v-if="p.id === active?.id" class="badge indigo">activo</span>
      </div>
      <button class="btn btn-ghost" style="margin-top: 8px" @click="switchOpen = false; createOpen = true">
        + Crear otro plan
      </button>
    </Sheet>

    <div v-if="toast" class="toast">{{ toast }}</div>
  </AppShell>
</template>
