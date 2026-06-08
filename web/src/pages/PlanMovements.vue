<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppNav from '../components/AppNav.vue'
import { api, getBootstrap, ensureBootstrap } from '../api'

const route = useRoute()
const planId = route.params.id

const KINDS = [
  { value: 'ingreso', label: 'Ingreso' },
  { value: 'deuda_informal', label: 'Deuda informal' },
  { value: 'prestamo', label: 'Préstamo' },
]

const movements = ref([])
const catalogs = ref({ currencies: [] })
const planName = ref('')
const error = ref('')
const loading = ref(false)
const editingId = ref(null) // null = modo crear

function blankForm() {
  return {
    kind: 'ingreso',
    currency_id: '',
    description: '',
    principal_amount: '',
    start_date: '',
    income_duration_months: '',
    installment_amount: '',
    installment_start_date: '',
    total_installments: '',
    financing_rate: '',
    overdue_rate: '',
    rates_add_vat: true,
  }
}

const form = ref(blankForm())

function defaultCurrency() {
  return (catalogs.value.currencies || []).find((c) => c.is_legal_tender)?.id ?? ''
}

function kindLabel(kind) {
  return KINDS.find((k) => k.value === kind)?.label ?? kind
}
function currencyName(id) {
  return catalogs.value.currencies?.find((c) => c.id === id)?.name ?? `#${id}`
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

async function loadPlanName() {
  try {
    const plans = await api.listPlans()
    planName.value = plans.find((p) => p.id === planId)?.name ?? ''
  } catch {
    planName.value = ''
  }
}

async function loadMovements() {
  error.value = ''
  loading.value = true
  try {
    movements.value = await api.listMovements(planId)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadCatalogs()
  await loadPlanName()
  await loadMovements()
})

function movementSummary(m) {
  if (m.kind === 'ingreso') {
    const dur = m.income_duration_months == null ? 'recurrente' : `${m.income_duration_months} mes(es)`
    return `Duración: ${dur} · desde ${m.start_date}`
  }
  if (m.kind === 'prestamo') {
    const fin = m.financing_rate ?? '—'
    const mora = m.overdue_rate ?? '—'
    const vat = m.rates_add_vat ? ' (+IVA)' : ''
    return `Cuota ${m.installment_amount} ×${m.total_installments} desde ${m.installment_start_date} · tasas ${fin}/${mora}${vat} · desembolso ${m.start_date}`
  }
  return `Desde ${m.start_date}`
}

function startCreate() {
  editingId.value = null
  form.value = blankForm()
  form.value.currency_id = defaultCurrency()
  error.value = ''
}

function startEdit(m) {
  editingId.value = m.id
  form.value = {
    kind: m.kind,
    currency_id: m.currency_id,
    description: m.description ?? '',
    principal_amount: m.principal_amount,
    start_date: m.start_date,
    income_duration_months: m.income_duration_months ?? '',
    installment_amount: m.installment_amount ?? '',
    installment_start_date: m.installment_start_date ?? '',
    total_installments: m.total_installments ?? '',
    financing_rate: m.financing_rate ?? '',
    overdue_rate: m.overdue_rate ?? '',
    rates_add_vat: m.rates_add_vat,
  }
  error.value = ''
}

function buildBody() {
  const f = form.value
  const body = {
    kind: f.kind,
    currency_id: Number(f.currency_id),
    description: f.description || null,
    principal_amount: String(f.principal_amount),
    start_date: f.start_date,
  }
  if (f.kind === 'ingreso') {
    body.income_duration_months =
      f.income_duration_months === '' ? null : Number(f.income_duration_months)
  } else if (f.kind === 'prestamo') {
    body.installment_amount = f.installment_amount === '' ? null : String(f.installment_amount)
    body.installment_start_date = f.installment_start_date || null
    body.total_installments = f.total_installments === '' ? null : Number(f.total_installments)
    body.financing_rate = f.financing_rate === '' ? null : String(f.financing_rate)
    body.overdue_rate = f.overdue_rate === '' ? null : String(f.overdue_rate)
    body.rates_add_vat = f.rates_add_vat
  }
  return body
}

async function submit() {
  error.value = ''
  try {
    if (editingId.value) {
      await api.updateMovement(planId, editingId.value, buildBody())
    } else {
      await api.createMovement(planId, buildBody())
    }
    startCreate()
    await loadMovements()
  } catch (e) {
    error.value = e.message
  }
}

async function remove(m) {
  error.value = ''
  try {
    await api.deleteMovement(planId, m.id)
    if (editingId.value === m.id) startCreate()
    await loadMovements()
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <AppNav />
    <div class="content">
      <div class="row">
        <h1>Movimientos</h1>
        <router-link class="ghost" to="/plans">← Planes</router-link>
      </div>
      <p class="muted">{{ planName || 'Plan' }}</p>

      <p v-if="error" class="error">{{ error }}</p>

      <!-- Form crear / editar -->
      <form class="income-form" @submit.prevent="submit">
        <div class="row">
          <label>{{ editingId ? 'Editar movimiento' : 'Nuevo movimiento' }}</label>
          <button v-if="editingId" type="button" class="ghost" @click="startCreate">Cancelar</button>
        </div>

        <div class="field">
          <label>Tipo {{ editingId ? '(no editable)' : '' }}</label>
          <select v-model="form.kind" :disabled="!!editingId">
            <option v-for="k in KINDS" :key="k.value" :value="k.value">{{ k.label }}</option>
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
          <label>Descripción</label>
          <input v-model="form.description" type="text" placeholder="Opcional" />
        </div>

        <div class="field">
          <label>{{ form.kind === 'prestamo' ? 'Monto del préstamo' : 'Monto' }}</label>
          <input v-model="form.principal_amount" type="text" inputmode="decimal" placeholder="45000.00" />
        </div>

        <div class="field">
          <label>{{ form.kind === 'prestamo' ? 'Fecha de desembolso' : 'Fecha de inicio' }}</label>
          <input v-model="form.start_date" type="date" />
        </div>

        <!-- ingreso -->
        <div v-if="form.kind === 'ingreso'" class="field">
          <label>Meses de duración (vacío = recurrente, 1 = único)</label>
          <input v-model="form.income_duration_months" type="number" min="1" placeholder="recurrente" />
        </div>

        <!-- prestamo -->
        <template v-if="form.kind === 'prestamo'">
          <div class="field">
            <label>Monto de la cuota</label>
            <input v-model="form.installment_amount" type="text" inputmode="decimal" placeholder="5000.00" />
          </div>
          <div class="field">
            <label>Primera cuota</label>
            <input v-model="form.installment_start_date" type="date" />
          </div>
          <div class="field">
            <label>Cantidad de cuotas</label>
            <input v-model="form.total_installments" type="number" min="1" placeholder="12" />
          </div>
          <div class="field">
            <label>Tasa de financiación (opcional)</label>
            <input v-model="form.financing_rate" type="text" inputmode="decimal" placeholder="3.50" />
          </div>
          <div class="field">
            <label>Tasa de mora (opcional)</label>
            <input v-model="form.overdue_rate" type="text" inputmode="decimal" placeholder="5.00" />
          </div>
          <label class="check">
            <input v-model="form.rates_add_vat" type="checkbox" />
            Las tasas llevan IVA
          </label>
        </template>

        <button class="primary" type="submit">{{ editingId ? 'Guardar cambios' : 'Crear' }}</button>
      </form>

      <!-- Lista -->
      <div class="row">
        <label>Movimientos del plan</label>
        <button class="ghost" :disabled="loading" @click="loadMovements">
          {{ loading ? 'Cargando…' : 'Refrescar' }}
        </button>
      </div>

      <p v-if="!movements.length" class="muted">Este plan todavía no tiene movimientos.</p>

      <div v-for="m in movements" :key="m.id" class="income-card">
        <div class="income-head">
          <span class="income-desc">
            {{ m.description || kindLabel(m.kind) }}
            <span class="badge">{{ kindLabel(m.kind) }}</span>
          </span>
          <span class="income-amount">{{ m.principal_amount }} {{ currencyName(m.currency_id) }}</span>
        </div>
        <p class="muted">{{ movementSummary(m) }}</p>
        <div class="income-actions">
          <button class="ghost" @click="startEdit(m)">Editar</button>
          <button class="ghost danger" @click="remove(m)">Borrar</button>
        </div>
      </div>
    </div>
  </div>
</template>
