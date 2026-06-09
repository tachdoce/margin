<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppNav from '../components/AppNav.vue'
import { api, getBootstrap, ensureBootstrap } from '../api'
import { formatMoney } from '../format'

const router = useRouter()

const plans = ref([])
const catalogs = ref({ currencies: [] })
const error = ref('')
const loading = ref(false)
const editingId = ref(null) // null = modo crear

function blankForm() {
  return {
    name: '',
    dial_amount: '',
    has_goal: false,
    goal_amount: '',
    select_on_create: true,
  }
}

const form = ref(blankForm())

// La lista viene ordenada por selected_at desc → el primero es el plan activo.
const activeId = computed(() => plans.value[0]?.id ?? null)

async function loadCatalogs() {
  let bs = getBootstrap()
  if (!bs) {
    try {
      bs = await ensureBootstrap()
    } catch {
      bs = null
    }
  }
  if (bs?.catalogs) catalogs.value = bs.catalogs
}

async function loadPlans() {
  error.value = ''
  loading.value = true
  try {
    plans.value = await api.listPlans()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadCatalogs()
  await loadPlans()
})

function currencyName(id) {
  return catalogs.value.currencies?.find((c) => c.id === id)?.name ?? `#${id}`
}

function goalSummary(plan) {
  if (plan.goal_kind === 'ahorro_total') {
    return `Objetivo: ahorro total de ${formatMoney(plan.goal_amount, plan.goal_currency_id)}`
  }
  return 'Sin objetivo'
}

function startCreate() {
  editingId.value = null
  form.value = blankForm()
  error.value = ''
}

function startEdit(plan) {
  editingId.value = plan.id
  form.value = {
    name: plan.name,
    dial_amount: plan.dial_amount,
    has_goal: plan.goal_kind === 'ahorro_total',
    goal_amount: plan.goal_amount ?? '',
    select_on_create: false,
  }
  error.value = ''
}

function buildBody() {
  const f = form.value
  const body = {
    name: f.name,
    dial_amount: String(f.dial_amount),
    goal_kind: f.has_goal ? 'ahorro_total' : null,
    goal_amount: f.has_goal ? String(f.goal_amount) : null,
  }
  if (!editingId.value) body.select_on_create = f.select_on_create
  return body
}

async function submit() {
  error.value = ''
  try {
    if (editingId.value) {
      await api.updatePlan(editingId.value, buildBody())
    } else {
      await api.createPlan(buildBody())
    }
    startCreate()
    await loadPlans()
  } catch (e) {
    error.value = e.message
  }
}

async function select(plan) {
  error.value = ''
  try {
    await api.selectPlan(plan.id)
    await loadPlans()
  } catch (e) {
    error.value = e.message
  }
}

async function remove(plan) {
  error.value = ''
  try {
    await api.deletePlan(plan.id)
    if (editingId.value === plan.id) startCreate()
    await loadPlans()
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <AppNav />
    <div class="content">
      <h1>Planes</h1>

      <p v-if="error" class="error">{{ error }}</p>

      <!-- Form crear / editar -->
      <form class="income-form" @submit.prevent="submit">
        <div class="row">
          <label>{{ editingId ? 'Editar plan' : 'Nuevo plan' }}</label>
          <button v-if="editingId" type="button" class="ghost" @click="startCreate">Cancelar</button>
        </div>

        <div class="field">
          <label>Nombre</label>
          <input v-model="form.name" type="text" placeholder="Plan agresivo" />
        </div>

        <div class="field">
          <label>Monto del dial</label>
          <input v-model="form.dial_amount" type="text" inputmode="decimal" placeholder="0.00" />
        </div>

        <div class="seg">
          <button
            type="button"
            class="seg-btn"
            :class="{ 'seg-active': !form.has_goal }"
            @click="form.has_goal = false"
          >
            Sin objetivo
          </button>
          <button
            type="button"
            class="seg-btn"
            :class="{ 'seg-active': form.has_goal }"
            @click="form.has_goal = true"
          >
            Ahorro total
          </button>
        </div>

        <div v-if="form.has_goal" class="field">
          <label>Monto del objetivo</label>
          <input v-model="form.goal_amount" type="text" inputmode="decimal" placeholder="100000.00" />
        </div>

        <label v-if="!editingId" class="check">
          <input v-model="form.select_on_create" type="checkbox" />
          Seleccionar este plan al crearlo
        </label>

        <button class="primary" type="submit">{{ editingId ? 'Guardar cambios' : 'Crear' }}</button>
      </form>

      <!-- Lista -->
      <div class="row">
        <label>Mis planes</label>
        <button class="ghost" :disabled="loading" @click="loadPlans">
          {{ loading ? 'Cargando…' : 'Refrescar' }}
        </button>
      </div>

      <p v-if="!plans.length" class="muted">Todavía no tenés planes.</p>

      <div v-for="plan in plans" :key="plan.id" class="income-card">
        <div class="income-head">
          <span class="income-desc">
            {{ plan.name }}
            <span v-if="plan.is_default" class="badge">default</span>
            <span v-if="plan.id === activeId" class="badge">activo</span>
          </span>
          <span class="income-amount">{{ formatMoney(plan.dial_amount, plan.dial_currency_id) }}</span>
        </div>
        <p class="muted">{{ goalSummary(plan) }}</p>
        <div class="income-actions">
          <button class="ghost" @click="startEdit(plan)">Editar</button>
          <button class="ghost accent" :disabled="plan.id === activeId" @click="select(plan)">
            {{ plan.id === activeId ? 'Activo' : 'Seleccionar' }}
          </button>
          <button
            v-if="!plan.is_default"
            class="ghost"
            @click="router.push(`/plans/${plan.id}/movements`)"
          >
            Movimientos
          </button>
          <button v-if="!plan.is_default" class="ghost danger" @click="remove(plan)">Borrar</button>
        </div>
      </div>
    </div>
  </div>
</template>
