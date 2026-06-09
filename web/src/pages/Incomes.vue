<script setup>
import { onMounted, ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import { api, getBootstrap, ensureBootstrap } from '../api'
import { formatMoney } from '../format'

const incomes = ref([])
const catalogs = ref({ income_types: [], currencies: [] })
const error = ref('')
const loading = ref(false)
const editingId = ref(null) // null = modo crear

function blankForm() {
  return {
    income_type_id: '',
    currency_id: '',
    amount: '',
    description: '',
    is_monthly_recurring: true,
    payment_day: '',
    first_income_date: '',
    total_months: '',
    shift_weekends: false,
  }
}

const form = ref(blankForm())

function defaultCurrency() {
  return (catalogs.value.currencies || []).find((c) => c.is_legal_tender)?.id ?? ''
}

async function loadCatalogs() {
  let bs = getBootstrap()
  if (!bs) {
    try {
      bs = await ensureBootstrap()
    } catch {
      bs = null
    }
  }
  if (bs?.catalogs) {
    catalogs.value = bs.catalogs
    if (!form.value.currency_id) form.value.currency_id = defaultCurrency()
  }
}

async function loadIncomes() {
  error.value = ''
  loading.value = true
  try {
    incomes.value = (await api.listIncomes()).incomes
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadCatalogs()
  await loadIncomes()
})

function typeName(id) {
  return catalogs.value.income_types?.find((t) => t.id === id)?.name ?? `#${id}`
}
function currencyName(id) {
  return catalogs.value.currencies?.find((c) => c.id === id)?.name ?? `#${id}`
}
function formSummary(inc) {
  return inc.is_monthly_recurring
    ? `Recurrente, día ${inc.payment_day}`
    : `Duración fija, ${inc.first_income_date} ×${inc.total_months}`
}

function startCreate() {
  editingId.value = null
  form.value = blankForm()
  form.value.currency_id = defaultCurrency()
  error.value = ''
}

function startEdit(inc) {
  editingId.value = inc.id
  form.value = {
    income_type_id: inc.income_type_id,
    currency_id: inc.currency_id,
    amount: inc.amount,
    description: inc.description,
    is_monthly_recurring: inc.is_monthly_recurring,
    payment_day: inc.payment_day ?? '',
    first_income_date: inc.first_income_date ?? '',
    total_months: inc.total_months ?? '',
    shift_weekends: inc.shift_weekends,
  }
  error.value = ''
}

function buildBody() {
  const f = form.value
  const body = {
    income_type_id: Number(f.income_type_id),
    currency_id: Number(f.currency_id),
    amount: String(f.amount),
    description: f.description,
    is_monthly_recurring: f.is_monthly_recurring,
    shift_weekends: f.shift_weekends,
  }
  if (f.is_monthly_recurring) {
    body.payment_day = f.payment_day === '' ? null : Number(f.payment_day)
    body.first_income_date = null
    body.total_months = null
  } else {
    body.payment_day = null
    body.first_income_date = f.first_income_date || null
    body.total_months = f.total_months === '' ? null : Number(f.total_months)
  }
  return body
}

async function submit() {
  error.value = ''
  try {
    if (editingId.value) {
      await api.updateIncome(editingId.value, buildBody())
    } else {
      await api.createIncome(buildBody())
    }
    startCreate()
    await loadIncomes()
  } catch (e) {
    error.value = e.message
  }
}

async function remove(inc) {
  error.value = ''
  try {
    await api.deleteIncome(inc.id)
    await loadIncomes()
  } catch (e) {
    error.value = e.message
  }
}

async function reactivate(inc) {
  error.value = ''
  try {
    await api.reactivateIncome(inc.id)
    await loadIncomes()
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <AppNav />
    <div class="content">
      <h1>Ingresos</h1>

      <p v-if="error" class="error">{{ error }}</p>

      <!-- Form crear / editar -->
      <form class="income-form" @submit.prevent="submit">
        <div class="row">
          <label>{{ editingId ? 'Editar ingreso' : 'Nuevo ingreso' }}</label>
          <button v-if="editingId" type="button" class="ghost" @click="startCreate">Cancelar</button>
        </div>

        <div class="field">
          <label>Tipo</label>
          <select v-model="form.income_type_id">
            <option value="" disabled>Elegí un tipo</option>
            <option v-for="t in catalogs.income_types" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>

        <div class="field">
          <label>Moneda</label>
          <select v-model="form.currency_id">
            <option value="" disabled>Elegí una moneda</option>
            <option v-for="c in catalogs.currencies" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>

        <div class="field">
          <label>Monto</label>
          <input v-model="form.amount" type="text" inputmode="decimal" placeholder="45000.00" />
        </div>

        <div class="field">
          <label>Descripción</label>
          <input v-model="form.description" type="text" placeholder="Sueldo principal" />
        </div>

        <div class="seg">
          <button
            type="button"
            class="seg-btn"
            :class="{ 'seg-active': form.is_monthly_recurring }"
            @click="form.is_monthly_recurring = true"
          >
            Recurrente
          </button>
          <button
            type="button"
            class="seg-btn"
            :class="{ 'seg-active': !form.is_monthly_recurring }"
            @click="form.is_monthly_recurring = false"
          >
            Duración fija
          </button>
        </div>

        <div v-if="form.is_monthly_recurring" class="field">
          <label>Día de cobro (1–31)</label>
          <input v-model="form.payment_day" type="number" min="1" max="31" placeholder="5" />
        </div>

        <template v-else>
          <div class="field">
            <label>Primer cobro</label>
            <input v-model="form.first_income_date" type="date" />
          </div>
          <div class="field">
            <label>Cantidad de meses</label>
            <input v-model="form.total_months" type="number" min="1" placeholder="1" />
          </div>
        </template>

        <label class="check">
          <input v-model="form.shift_weekends" type="checkbox" />
          Correr fechas que caen fin de semana
        </label>

        <button class="primary" type="submit">{{ editingId ? 'Guardar cambios' : 'Crear' }}</button>
      </form>

      <!-- Lista -->
      <div class="row">
        <label>Mis ingresos</label>
        <button class="ghost" :disabled="loading" @click="loadIncomes">
          {{ loading ? 'Cargando…' : 'Refrescar' }}
        </button>
      </div>

      <p v-if="!incomes.length" class="muted">Todavía no cargaste ingresos.</p>

      <div v-for="inc in incomes" :key="inc.id" class="income-card" :class="{ deleted: inc.is_deleted }">
        <div class="income-head">
          <span class="income-desc">
            {{ inc.description }}
            <span v-if="inc.is_deleted" class="badge">borrado</span>
          </span>
          <span class="income-amount">{{ formatMoney(inc.amount, inc.currency_id) }}</span>
        </div>
        <p class="muted">{{ typeName(inc.income_type_id) }} · {{ formSummary(inc) }}</p>
        <div class="income-actions">
          <template v-if="!inc.is_deleted">
            <button class="ghost" @click="startEdit(inc)">Editar</button>
            <button class="ghost danger" @click="remove(inc)">Borrar</button>
          </template>
          <button v-else class="ghost accent" @click="reactivate(inc)">Reactivar</button>
        </div>
      </div>
    </div>
  </div>
</template>
