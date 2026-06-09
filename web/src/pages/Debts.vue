<script setup>
import { computed, onMounted, ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import { api, getBootstrap, ensureBootstrap } from '../api'
import { formatMoney } from '../format'

const debts = ref([])
const catalogs = ref({ obligation_types: [], priority_levels: [], currencies: [], institutions: [], review_finding_codes: [] })
const error = ref('')
const loading = ref(false)
const editingId = ref(null) // null = modo crear

function blankForm() {
  return {
    obligation_type_id: '',
    priority_level: '',
    institution_id: '',
    description: '',
    currency_id: '',
    amount: '',
    schedule_mode: 'cronograma', // 'cronograma' | 'unico'
    total_installments: '',
    first_due_date: '',
    due_day: '',
    financing_rate: '',
    overdue_rate: '',
    rates_add_vat: true,
    shift_weekends: false,
  }
}

const form = ref(blankForm())

const debtTypes = computed(() =>
  (catalogs.value.obligation_types || []).filter(
    (t) => t.obligation_kind === 'deuda' || t.obligation_kind === 'deuda_abierta',
  ),
)
const priorities = computed(() => (catalogs.value.priority_levels || []).filter((p) => p.level !== 1))

function typeKind(id) {
  return catalogs.value.obligation_types?.find((t) => t.id === Number(id))?.obligation_kind
}
const selectedKind = computed(() => typeKind(form.value.obligation_type_id))

function defaultCurrency() {
  return (catalogs.value.currencies || []).find((c) => c.is_legal_tender)?.id ?? ''
}
function typeName(id) {
  return catalogs.value.obligation_types?.find((t) => t.id === id)?.name ?? `#${id}`
}
function currencyName(id) {
  return catalogs.value.currencies?.find((c) => c.id === id)?.name ?? `#${id}`
}
function findingMessage(code) {
  return catalogs.value.review_finding_codes?.find((c) => c.code === code)?.message ?? code
}

function onTypeChange() {
  const t = debtTypes.value.find((t) => t.id === Number(form.value.obligation_type_id))
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

async function loadDebts() {
  error.value = ''
  loading.value = true
  try {
    debts.value = (await api.listDebts()).debts
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadCatalogs()
  await loadDebts()
})

function debtSummary(d) {
  if (typeKind(d.obligation_type_id) === 'deuda_abierta') return 'Deuda abierta (sin fecha)'
  if (d.total_installments != null)
    return `Cronograma: ${d.total_installments} cuotas, día ${d.due_day}, desde ${d.first_due_date}`
  return `Pago único: ${d.first_due_date}`
}

function startCreate() {
  editingId.value = null
  form.value = blankForm()
  form.value.currency_id = defaultCurrency()
  error.value = ''
}

function startEdit(d) {
  editingId.value = d.id
  form.value = {
    obligation_type_id: d.obligation_type_id,
    priority_level: d.priority_level,
    institution_id: d.institution_id ?? '',
    description: d.description,
    currency_id: d.currency_id,
    amount: d.amount,
    schedule_mode: d.total_installments != null ? 'cronograma' : 'unico',
    total_installments: d.total_installments ?? '',
    first_due_date: d.first_due_date ?? '',
    due_day: d.due_day ?? '',
    financing_rate: d.financing_rate ?? '',
    overdue_rate: d.overdue_rate ?? '',
    rates_add_vat: d.rates_add_vat,
    shift_weekends: d.shift_weekends,
  }
  error.value = ''
}

function buildBody() {
  const f = form.value
  const kind = selectedKind.value
  const body = {
    obligation_type_id: Number(f.obligation_type_id),
    priority_level: Number(f.priority_level),
    description: f.description,
    currency_id: Number(f.currency_id),
    amount: String(f.amount),
  }
  if (kind === 'deuda') {
    body.institution_id = f.institution_id === '' ? null : Number(f.institution_id)
    body.shift_weekends = f.shift_weekends
    body.rates_add_vat = f.rates_add_vat
    body.financing_rate = f.financing_rate === '' ? null : String(f.financing_rate)
    body.overdue_rate = f.overdue_rate === '' ? null : String(f.overdue_rate)
    if (f.schedule_mode === 'cronograma') {
      body.total_installments = f.total_installments === '' ? null : Number(f.total_installments)
      body.first_due_date = f.first_due_date || null
      body.due_day = f.due_day === '' ? null : Number(f.due_day)
    } else {
      body.total_installments = null
      body.first_due_date = f.first_due_date || null
      body.due_day = null
    }
  }
  return body
}

async function submit() {
  error.value = ''
  try {
    if (editingId.value) {
      const body = buildBody()
      delete body.obligation_type_id // el tipo no se cambia desde la edición
      await api.updateDebt(editingId.value, body)
    } else {
      await api.createDebt(buildBody())
    }
    startCreate()
    await loadDebts()
  } catch (e) {
    error.value = e.message
  }
}

async function acknowledge(d) {
  error.value = ''
  try {
    await api.acknowledgeObligation(d.id)
    await loadDebts()
  } catch (e) {
    error.value = e.message
  }
}

async function toggleClosed(d) {
  error.value = ''
  try {
    await api.updateDebt(d.id, { is_closed: !d.is_closed })
    await loadDebts()
  } catch (e) {
    error.value = e.message
  }
}

async function remove(d) {
  error.value = ''
  try {
    await api.deleteDebt(d.id)
    if (editingId.value === d.id) startCreate()
    await loadDebts()
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <AppNav />
    <div class="content">
      <h1>Deudas</h1>

      <p v-if="error" class="error">{{ error }}</p>

      <!-- Form crear / editar -->
      <form class="income-form" @submit.prevent="submit">
        <div class="row">
          <label>{{ editingId ? 'Editar deuda' : 'Nueva deuda' }}</label>
          <button v-if="editingId" type="button" class="ghost" @click="startCreate">Cancelar</button>
        </div>

        <div class="field">
          <label>Tipo {{ editingId ? '(no editable)' : '' }}</label>
          <select v-model="form.obligation_type_id" :disabled="!!editingId" @change="onTypeChange">
            <option value="" disabled>Elegí un tipo</option>
            <option v-for="t in debtTypes" :key="t.id" :value="t.id">
              {{ t.name }} ({{ t.obligation_kind === 'deuda_abierta' ? 'abierta' : 'deuda' }})
            </option>
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
          <input v-model="form.description" type="text" placeholder="Préstamo personal banco" />
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
          <input v-model="form.amount" type="text" inputmode="decimal" placeholder="6250.00" />
        </div>

        <!-- Solo deuda (no deuda_abierta) -->
        <template v-if="selectedKind === 'deuda'">
          <div class="field">
            <label>Institución (opcional)</label>
            <select v-model="form.institution_id">
              <option value="">Sin institución</option>
              <option v-for="i in catalogs.institutions" :key="i.id" :value="i.id">{{ i.name }}</option>
            </select>
          </div>

          <div class="seg">
            <button
              type="button"
              class="seg-btn"
              :class="{ 'seg-active': form.schedule_mode === 'cronograma' }"
              @click="form.schedule_mode = 'cronograma'"
            >
              Cronograma
            </button>
            <button
              type="button"
              class="seg-btn"
              :class="{ 'seg-active': form.schedule_mode === 'unico' }"
              @click="form.schedule_mode = 'unico'"
            >
              Pago único
            </button>
          </div>

          <template v-if="form.schedule_mode === 'cronograma'">
            <div class="field">
              <label>Cantidad de cuotas</label>
              <input v-model="form.total_installments" type="number" min="1" placeholder="24" />
            </div>
            <div class="field">
              <label>Primera cuota (mes/año)</label>
              <input v-model="form.first_due_date" type="date" />
            </div>
            <div class="field">
              <label>Día de vencimiento (1–31)</label>
              <input v-model="form.due_day" type="number" min="1" max="31" placeholder="10" />
            </div>
          </template>
          <div v-else class="field">
            <label>Fecha del pago</label>
            <input v-model="form.first_due_date" type="date" />
          </div>

          <div class="field">
            <label>Tasa de financiación (opcional)</label>
            <input v-model="form.financing_rate" type="text" inputmode="decimal" placeholder="45.00" />
          </div>
          <div class="field">
            <label>Tasa de mora (opcional)</label>
            <input v-model="form.overdue_rate" type="text" inputmode="decimal" placeholder="60.00" />
          </div>
          <label class="check">
            <input v-model="form.rates_add_vat" type="checkbox" />
            Las tasas llevan IVA
          </label>
          <label class="check">
            <input v-model="form.shift_weekends" type="checkbox" />
            Correr vencimientos que caen fin de semana
          </label>
        </template>

        <button class="primary" type="submit">{{ editingId ? 'Guardar cambios' : 'Crear' }}</button>
      </form>

      <!-- Lista -->
      <div class="row">
        <label>Mis deudas</label>
        <button class="ghost" :disabled="loading" @click="loadDebts">
          {{ loading ? 'Cargando…' : 'Refrescar' }}
        </button>
      </div>

      <p v-if="!debts.length" class="muted">Todavía no cargaste deudas.</p>

      <div v-for="d in debts" :key="d.id" class="income-card" :class="{ deleted: d.is_closed }">
        <div class="income-head">
          <span class="income-desc">
            {{ d.description }}
            <span v-if="d.is_closed" class="badge">cerrado</span>
          </span>
          <span class="income-amount">{{ formatMoney(d.amount, d.currency_id) }}</span>
        </div>
        <p class="muted">{{ typeName(d.obligation_type_id) }} · {{ debtSummary(d) }}</p>

        <p v-if="!d.is_ready && d.review_findings.length" class="error">
          ⚠ {{ d.review_findings.map(findingMessage).join(' · ') }}
        </p>

        <div class="income-actions">
          <button class="ghost" @click="startEdit(d)">Editar</button>
          <button v-if="d.review_findings.length" class="ghost accent" @click="acknowledge(d)">
            Reconocer
          </button>
          <button class="ghost" @click="toggleClosed(d)">{{ d.is_closed ? 'Reabrir' : 'Cerrar' }}</button>
          <button class="ghost danger" @click="remove(d)">Borrar</button>
        </div>
      </div>
    </div>
  </div>
</template>
