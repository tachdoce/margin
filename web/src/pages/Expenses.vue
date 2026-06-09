<script setup>
import { computed, onMounted, ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import { api, getBootstrap, ensureBootstrap } from '../api'
import { formatMoney } from '../format'

const expenses = ref([])
const catalogs = ref({ obligation_types: [], priority_levels: [], currencies: [] })
const error = ref('')
const loading = ref(false)
const editingId = ref(null) // null = modo crear

function blankForm() {
  return {
    obligation_type_id: '',
    priority_level: '',
    description: '',
    is_monthly_recurring: true,
    due_day: '',
    first_due_date: '',
    currency_id: '',
    amount: '',
    shift_weekends: false,
  }
}

const form = ref(blankForm())

// tipos de gasto (filtrados del catálogo) y prioridades elegibles (sin el nivel 1 Ineludible)
const gastoTypes = computed(() =>
  (catalogs.value.obligation_types || []).filter((t) => t.obligation_kind === 'gasto'),
)
const priorities = computed(() =>
  (catalogs.value.priority_levels || []).filter((p) => p.level !== 1),
)

function defaultCurrency() {
  return (catalogs.value.currencies || []).find((c) => c.is_legal_tender)?.id ?? ''
}

function typeName(id) {
  return catalogs.value.obligation_types?.find((t) => t.id === id)?.name ?? `#${id}`
}
function currencyName(id) {
  return catalogs.value.currencies?.find((c) => c.id === id)?.name ?? `#${id}`
}

// al elegir el tipo, precargar la prioridad con el default del tipo (el usuario la puede cambiar)
function onTypeChange() {
  const t = gastoTypes.value.find((t) => t.id === Number(form.value.obligation_type_id))
  if (t && !editingId.value) form.value.priority_level = t.default_priority_level
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

async function loadExpenses() {
  error.value = ''
  loading.value = true
  try {
    expenses.value = (await api.listExpenses()).expenses
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadCatalogs()
  await loadExpenses()
})

function formSummary(exp) {
  return exp.is_monthly_recurring
    ? `Recurrente, día ${exp.due_day}`
    : `Único, ${exp.first_due_date}`
}

function startCreate() {
  editingId.value = null
  form.value = blankForm()
  form.value.currency_id = defaultCurrency()
  error.value = ''
}

function startEdit(exp) {
  editingId.value = exp.id
  form.value = {
    obligation_type_id: exp.obligation_type_id,
    priority_level: exp.priority_level,
    description: exp.description,
    is_monthly_recurring: exp.is_monthly_recurring,
    due_day: exp.due_day ?? '',
    first_due_date: exp.first_due_date ?? '',
    currency_id: exp.currency_id,
    amount: exp.amount,
    shift_weekends: exp.shift_weekends,
  }
  error.value = ''
}

function buildBody() {
  const f = form.value
  const body = {
    obligation_type_id: Number(f.obligation_type_id),
    priority_level: Number(f.priority_level),
    description: f.description,
    is_monthly_recurring: f.is_monthly_recurring,
    currency_id: Number(f.currency_id),
    amount: String(f.amount),
    shift_weekends: f.shift_weekends,
  }
  if (f.is_monthly_recurring) {
    body.due_day = f.due_day === '' ? null : Number(f.due_day)
    body.first_due_date = null
  } else {
    body.due_day = null
    body.first_due_date = f.first_due_date || null
  }
  return body
}

async function submit() {
  error.value = ''
  try {
    if (editingId.value) {
      await api.updateExpense(editingId.value, buildBody())
    } else {
      await api.createExpense(buildBody())
    }
    startCreate()
    await loadExpenses()
  } catch (e) {
    error.value = e.message
  }
}

async function toggleClosed(exp) {
  error.value = ''
  try {
    await api.updateExpense(exp.id, { is_closed: !exp.is_closed })
    await loadExpenses()
  } catch (e) {
    error.value = e.message
  }
}

async function remove(exp) {
  error.value = ''
  try {
    await api.deleteExpense(exp.id)
    if (editingId.value === exp.id) startCreate()
    await loadExpenses()
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <AppNav />
    <div class="content">
      <h1>Gastos</h1>

      <p v-if="error" class="error">{{ error }}</p>

      <!-- Form crear / editar -->
      <form class="income-form" @submit.prevent="submit">
        <div class="row">
          <label>{{ editingId ? 'Editar gasto' : 'Nuevo gasto' }}</label>
          <button v-if="editingId" type="button" class="ghost" @click="startCreate">Cancelar</button>
        </div>

        <div class="field">
          <label>Tipo</label>
          <select v-model="form.obligation_type_id" @change="onTypeChange">
            <option value="" disabled>Elegí un tipo</option>
            <option v-for="t in gastoTypes" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>

        <div class="field">
          <label>Prioridad</label>
          <select v-model="form.priority_level">
            <option value="" disabled>Elegí una prioridad</option>
            <option v-for="p in priorities" :key="p.level" :value="p.level">{{ p.name }}</option>
          </select>
        </div>

        <div class="field">
          <label>Descripción (mín. 8)</label>
          <input v-model="form.description" type="text" placeholder="Alquiler depto" />
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
          <input v-model="form.amount" type="text" inputmode="decimal" placeholder="32000.00" />
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
            Único
          </button>
        </div>

        <div v-if="form.is_monthly_recurring" class="field">
          <label>Día de vencimiento (1–31)</label>
          <input v-model="form.due_day" type="number" min="1" max="31" placeholder="10" />
        </div>
        <div v-else class="field">
          <label>Fecha del gasto</label>
          <input v-model="form.first_due_date" type="date" />
        </div>

        <label class="check">
          <input v-model="form.shift_weekends" type="checkbox" />
          Correr vencimientos que caen fin de semana
        </label>

        <button class="primary" type="submit">{{ editingId ? 'Guardar cambios' : 'Crear' }}</button>
      </form>

      <!-- Lista -->
      <div class="row">
        <label>Mis gastos</label>
        <button class="ghost" :disabled="loading" @click="loadExpenses">
          {{ loading ? 'Cargando…' : 'Refrescar' }}
        </button>
      </div>

      <p v-if="!expenses.length" class="muted">Todavía no cargaste gastos.</p>

      <div v-for="exp in expenses" :key="exp.id" class="income-card" :class="{ deleted: exp.is_closed }">
        <div class="income-head">
          <span class="income-desc">
            {{ exp.description }}
            <span v-if="exp.is_closed" class="badge">cerrado</span>
          </span>
          <span class="income-amount">{{ formatMoney(exp.amount, exp.currency_id) }}</span>
        </div>
        <p class="muted">{{ typeName(exp.obligation_type_id) }} · {{ formSummary(exp) }}</p>
        <div class="income-actions">
          <button class="ghost" @click="startEdit(exp)">Editar</button>
          <button class="ghost accent" @click="toggleClosed(exp)">
            {{ exp.is_closed ? 'Reabrir' : 'Cerrar' }}
          </button>
          <button class="ghost danger" @click="remove(exp)">Borrar</button>
        </div>
      </div>
    </div>
  </div>
</template>
