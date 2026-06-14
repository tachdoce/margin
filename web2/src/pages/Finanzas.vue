<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import Sheet from '../components/Sheet.vue'
import { api, ensureBootstrap, getBootstrap } from '../api'
import { formatMoney, currencyName, defaultCurrencyId } from '../format'

const tab = ref('ingresos') // 'ingresos' | 'deudas'
const incomes = ref([])
const debts = ref([])
const catalogs = ref({ currencies: [], income_types: [], obligation_types: [], priority_levels: [] })
const loading = ref(true)
const error = ref('')
const toast = ref('')

const sheetOpen = ref(false)
const saving = ref(false)
const form = reactive(blankForm())

function blankForm() {
  return {
    description: '',
    amount: '',
    currency_id: '',
    // ingreso
    income_type_id: '',
    is_monthly_recurring: true,
    payment_day: '',
    // deuda
    obligation_type_id: '',
    priority_level: '',
    financing_rate: '',
    in_installments: false,
    total_installments: '',
    due_day: '',
  }
}

function flash(msg) {
  toast.value = msg
  setTimeout(() => (toast.value = ''), 2200)
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const bs = await ensureBootstrap()
    if (bs?.catalogs) catalogs.value = bs.catalogs
    const [inc, deb] = await Promise.all([api.listIncomes(), api.listDebts()])
    incomes.value = inc.incomes ?? []
    debts.value = deb.debts ?? []
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

function obTypeName(id) {
  return catalogs.value.obligation_types?.find((t) => t.id === id)?.name ?? 'Deuda'
}
function incTypeName(id) {
  return catalogs.value.income_types?.find((t) => t.id === id)?.name ?? 'Ingreso'
}

function incomeMeta(i) {
  return i.is_monthly_recurring
    ? `${incTypeName(i.income_type_id)} · recurrente, día ${i.payment_day}`
    : `${incTypeName(i.income_type_id)} · ${i.total_months} mes(es)`
}

function openSheet() {
  Object.assign(form, blankForm())
  form.currency_id = defaultCurrencyId() ?? ''
  if (tab.value === 'ingresos') {
    form.income_type_id = catalogs.value.income_types?.find((t) => t.visible !== false)?.id ?? ''
  } else {
    const t = catalogs.value.obligation_types?.find((t) => t.visible !== false)
    form.obligation_type_id = t?.id ?? ''
    form.priority_level = t?.default_priority_level ?? catalogs.value.priority_levels?.[0]?.level ?? ''
  }
  error.value = ''
  sheetOpen.value = true
}

function buildIncomeBody() {
  const body = {
    income_type_id: Number(form.income_type_id),
    currency_id: Number(form.currency_id),
    amount: String(form.amount),
    description: form.description,
    is_monthly_recurring: form.is_monthly_recurring,
  }
  if (form.is_monthly_recurring) {
    body.payment_day = form.payment_day === '' ? null : Number(form.payment_day)
  }
  return body
}

function buildDebtBody() {
  const body = {
    obligation_type_id: Number(form.obligation_type_id),
    priority_level: Number(form.priority_level),
    description: form.description,
    currency_id: Number(form.currency_id),
    amount: String(form.amount),
    rates_add_vat: true,
    shift_weekends: false,
    financing_rate: form.financing_rate === '' ? null : String(form.financing_rate),
    overdue_rate: null,
  }
  if (form.in_installments) {
    body.total_installments = form.total_installments === '' ? null : Number(form.total_installments)
    body.due_day = form.due_day === '' ? null : Number(form.due_day)
  } else {
    body.total_installments = null
    body.due_day = null
  }
  return body
}

async function submit() {
  error.value = ''
  saving.value = true
  try {
    if (tab.value === 'ingresos') await api.createIncome(buildIncomeBody())
    else await api.createDebt(buildDebtBody())
    sheetOpen.value = false
    flash(tab.value === 'ingresos' ? 'Ingreso agregado' : 'Deuda agregada')
    await loadAll()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function removeItem(item) {
  error.value = ''
  try {
    if (tab.value === 'ingresos') await api.deleteIncome(item.id)
    else await api.deleteDebt(item.id)
    await loadAll()
  } catch (e) {
    error.value = e.message
  }
}

const list = computed(() => (tab.value === 'ingresos' ? incomes.value : debts.value))
</script>

<template>
  <AppShell title="Finanzas">
    <div class="segmented">
      <button :class="{ active: tab === 'ingresos' }" @click="tab = 'ingresos'">Ingresos</button>
      <button :class="{ active: tab === 'deudas' }" @click="tab = 'deudas'">Deudas</button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <div v-if="loading" class="muted">Cargando…</div>

    <template v-else>
      <div v-if="!list.length" class="empty">
        <div class="ic">{{ tab === 'ingresos' ? '💰' : '📄' }}</div>
        <h3>Todavía no cargaste {{ tab === 'ingresos' ? 'ingresos' : 'deudas' }}</h3>
        <p>{{ tab === 'ingresos'
          ? 'Agregá tu sueldo o cualquier entrada de plata.'
          : 'Agregá tus tarjetas, préstamos o lo que debas.' }}</p>
        <button class="btn btn-primary" style="max-width: 220px; margin: 0 auto" @click="openSheet">
          + Agregar {{ tab === 'ingresos' ? 'ingreso' : 'deuda' }}
        </button>
      </div>

      <template v-else>
        <!-- Ingresos -->
        <div v-if="tab === 'ingresos'">
          <div v-for="i in incomes" :key="i.id" class="item">
            <span class="ava green">💰</span>
            <div class="grow">
              <div class="title">{{ i.description }}</div>
              <div class="meta">{{ incomeMeta(i) }}</div>
            </div>
            <span class="amount">{{ formatMoney(i.amount, i.currency_id) }}</span>
          </div>
        </div>
        <!-- Deudas -->
        <div v-else>
          <div v-for="d in debts" :key="d.id" class="item">
            <span class="ava red">📄</span>
            <div class="grow">
              <div class="title">{{ d.description }}</div>
              <div class="meta">{{ obTypeName(d.obligation_type_id) }} · {{ currencyName(d.currency_id) }}</div>
            </div>
            <span class="amount">{{ formatMoney(d.amount, d.currency_id) }}</span>
          </div>
        </div>
      </template>
    </template>

    <button class="fab" @click="openSheet">+</button>

    <!-- Hoja de alta -->
    <Sheet v-model="sheetOpen" :title="tab === 'ingresos' ? 'Nuevo ingreso' : 'Nueva deuda'">
      <p v-if="error" class="error-banner">{{ error }}</p>
      <div class="field">
        <label>Descripción</label>
        <input v-model="form.description" type="text" :placeholder="tab === 'ingresos' ? 'Sueldo' : 'Tarjeta Visa'" />
        <div class="hint">Mínimo 3 letras.</div>
      </div>
      <div class="field">
        <label>Monto</label>
        <input v-model="form.amount" type="text" inputmode="decimal" placeholder="50000" />
      </div>
      <div class="field">
        <label>Moneda</label>
        <select v-model="form.currency_id">
          <option v-for="c in catalogs.currencies" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>

      <!-- Ingreso -->
      <template v-if="tab === 'ingresos'">
        <div class="field">
          <label>Tipo</label>
          <select v-model="form.income_type_id">
            <option v-for="t in catalogs.income_types" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>
        <label class="check">
          <input v-model="form.is_monthly_recurring" type="checkbox" />
          Lo cobro todos los meses
        </label>
        <div v-if="form.is_monthly_recurring" class="field">
          <label>Día de cobro</label>
          <input v-model="form.payment_day" type="number" min="1" max="31" placeholder="5" />
        </div>
      </template>

      <!-- Deuda -->
      <template v-else>
        <div class="field">
          <label>Tipo</label>
          <select v-model="form.obligation_type_id">
            <option v-for="t in catalogs.obligation_types" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>
        <div class="field">
          <label>Tasa de financiación mensual (opcional)</label>
          <input v-model="form.financing_rate" type="text" inputmode="decimal" placeholder="ej. 4.5" />
          <div class="hint">El % que te cobran por mes si no la pagás entera.</div>
        </div>
        <label class="check">
          <input v-model="form.in_installments" type="checkbox" />
          La pago en cuotas
        </label>
        <template v-if="form.in_installments">
          <div class="field">
            <label>Cantidad de cuotas</label>
            <input v-model="form.total_installments" type="number" min="1" placeholder="12" />
          </div>
          <div class="field">
            <label>Día de vencimiento</label>
            <input v-model="form.due_day" type="number" min="1" max="31" placeholder="10" />
          </div>
        </template>
      </template>

      <button class="btn btn-primary" :disabled="saving" @click="submit">
        {{ saving ? 'Guardando…' : 'Guardar' }}
      </button>
    </Sheet>

    <div v-if="toast" class="toast">{{ toast }}</div>
  </AppShell>
</template>
