<script setup>
import { onMounted, reactive, ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import { api, getBootstrap, ensureBootstrap } from '../api'
import { formatMoney } from '../format'

const catalogs = ref({ currencies: [] })
const plans = ref([])
const selectedPlanId = ref('')
const timeline = ref(null) // { months: [...], open_debts: [...] } | null
const openMonth = ref(null) // acordeón: solo un mes abierto a la vez
const error = ref('')
const notice = ref('')

function money0(x) {
  return Math.round(Number(x)) // sin centavos
}
function balanceDisplay(x) {
  return Math.round(Math.abs(Number(x))) // sin signo (el color comunica el sentido)
}
function isNegative(x) {
  return Number(x) < 0
}
function isSettled(e) {
  // cubierta por pagos/cobros reales → no hay nada que hacer
  return Number(e.amount) > 0 && Number(e.paid_real) >= Number(e.amount)
}
const currentMonth = (() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
})()
function isPastMonth(monthStr) {
  return monthStr < currentMonth // "YYYY-MM" compara lexicográficamente
}
function toggleMonth(key) {
  openMonth.value = openMonth.value === key ? null : key
}

// edición de monto inline (entries de gasto)
const editAmountId = ref(null)
const amountDraft = ref('')

// modal de pagos
const payEntry = ref(null) // la entry abierta | null
const payList = ref([])
const payForm = reactive({ amount: '', note: '', planned: false, planned_date: '' })
const editPayId = ref(null)
const editPayDraft = reactive({ amount: '', note: '', planned_date: '' })

const EDITABLE_TYPES = ['gasto']

function currencyName(id) {
  return catalogs.value.currencies?.find((c) => c.id === id)?.name ?? (id == null ? '' : `#${id}`)
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
  if (bs?.catalogs) catalogs.value = bs.catalogs
}

async function loadPlans() {
  try {
    plans.value = await api.listPlans()
    if (!selectedPlanId.value && plans.value.length) selectedPlanId.value = plans.value[0].id
  } catch (e) {
    error.value = e.message
  }
}

async function loadTimeline() {
  if (!selectedPlanId.value) return
  error.value = ''
  try {
    timeline.value = await api.getTimeline(selectedPlanId.value)
    openMonth.value = timeline.value.months[0]?.month ?? null
  } catch (e) {
    error.value = e.message
  }
}

onMounted(async () => {
  await loadCatalogs()
  await loadPlans()
  await loadTimeline()
})

// --- editar monto de una entry (gasto) ---
function startEditAmount(entry) {
  editAmountId.value = entry.id
  amountDraft.value = entry.amount
}
function cancelEditAmount() {
  editAmountId.value = null
}
async function saveAmount(entry) {
  error.value = ''
  try {
    await api.updateEntry(entry.id, { amount: amountDraft.value })
    editAmountId.value = null
    notice.value = 'Monto actualizado.'
    await loadTimeline()
  } catch (e) {
    error.value = e.message
  }
}

// --- pagos ---
async function openPayments(entry) {
  payEntry.value = entry
  Object.assign(payForm, { amount: '', note: '', planned: false, planned_date: '' })
  editPayId.value = null
  await loadPayments()
}
function closePayments() {
  payEntry.value = null
  payList.value = []
}
async function loadPayments() {
  error.value = ''
  try {
    payList.value = await api.listPayments(payEntry.value.id, selectedPlanId.value)
  } catch (e) {
    error.value = e.message
  }
}
async function submitPayment() {
  error.value = ''
  const body = { amount: payForm.amount, note: payForm.note || null }
  if (payForm.planned) {
    body.plan_id = selectedPlanId.value
    body.planned_date = payForm.planned_date || null
  }
  try {
    await api.createPayment(payEntry.value.id, body)
    Object.assign(payForm, { amount: '', note: '', planned: false, planned_date: '' })
    await loadPayments()
    await loadTimeline()
  } catch (e) {
    error.value = e.message
  }
}
function startEditPay(p) {
  editPayId.value = p.id
  Object.assign(editPayDraft, { amount: p.amount, note: p.note ?? '', planned_date: p.planned_date ?? '' })
}
async function saveEditPay(p) {
  error.value = ''
  const body = { amount: editPayDraft.amount, note: editPayDraft.note || null }
  if (p.is_planned) body.planned_date = editPayDraft.planned_date || null
  try {
    await api.updatePayment(payEntry.value.id, p.id, body)
    editPayId.value = null
    await loadPayments()
    await loadTimeline()
  } catch (e) {
    error.value = e.message
  }
}
async function delPay(p) {
  error.value = ''
  try {
    await api.deletePayment(payEntry.value.id, p.id)
    await loadPayments()
    await loadTimeline()
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <AppNav />
    <div class="content">
      <h1>Flujo de caja</h1>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="notice" class="muted">{{ notice }}</p>

      <div class="field">
        <label>Plan</label>
        <select v-model="selectedPlanId" @change="loadTimeline">
          <option v-for="p in plans" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>

      <p v-if="timeline && !timeline.months.length && !timeline.open_debts.length" class="muted">
        Sin movimientos para este plan.
      </p>

      <!-- meses -->
      <div v-for="m in timeline?.months || []" :key="m.month" class="income-card">
        <div class="income-head" style="cursor: pointer" @click="toggleMonth(m.month)">
          <span class="income-desc">{{ openMonth === m.month ? '▾' : '▸' }} {{ m.month }}</span>
          <span
            v-if="!isPastMonth(m.month)"
            class="income-amount"
            :class="{ accent: !isNegative(m.balance), danger: isNegative(m.balance) }"
          >
            balance {{ balanceDisplay(m.balance) }}
          </span>
        </div>
        <template v-if="openMonth === m.month">
          <p class="muted">ingresos {{ money0(m.total_income) }} · egresos {{ money0(m.total_expenses) }}</p>

          <div v-if="m.incomes.length">
            <div class="row"><label>Ingresos</label></div>
            <div v-for="e in m.incomes" :key="e.id" class="entry" :class="{ settled: isSettled(e) }">
              <div class="income-head">
                <span class="income-desc">
              {{ e.description }} · {{ e.event_date }}
              <span v-if="isSettled(e)" class="badge badge-ok">✓ saldado</span>
            </span>
                <span class="income-amount">{{ formatMoney(e.amount, e.currency_id) }}</span>
              </div>
              <p class="muted">cobrado {{ formatMoney(e.paid_real, e.currency_id) }} · planificado {{ formatMoney(e.planned_amount, e.currency_id) }}</p>
              <button class="ghost" type="button" @click="openPayments(e)">Cobros</button>
            </div>
          </div>

          <div v-if="m.expenses.length">
            <div class="row"><label>Egresos</label></div>
            <div v-for="e in m.expenses" :key="e.id" class="entry" :class="{ settled: isSettled(e) }">
              <div class="income-head">
                <span class="income-desc">
              {{ e.description }} · {{ e.event_date }}
              <span v-if="isSettled(e)" class="badge badge-ok">✓ saldado</span>
            </span>
                <span class="income-amount">{{ formatMoney(e.amount, e.currency_id) }}</span>
              </div>
              <p class="muted">pagado {{ formatMoney(e.paid_real, e.currency_id) }} · planificado {{ formatMoney(e.planned_amount, e.currency_id) }}</p>
              <div v-if="editAmountId === e.id" class="field-row">
                <input v-model="amountDraft" type="text" inputmode="decimal" />
                <button class="primary" type="button" @click="saveAmount(e)">Guardar</button>
                <button class="ghost" type="button" @click="cancelEditAmount">Cancelar</button>
              </div>
              <div v-else class="income-actions">
                <button class="ghost" type="button" @click="openPayments(e)">Pagos</button>
                <button v-if="EDITABLE_TYPES.includes(e.source_type)" class="ghost accent" type="button" @click="startEditAmount(e)">
                  Editar monto
                </button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- open_debts -->
      <div v-if="timeline?.open_debts?.length" class="income-card">
        <div class="row"><label>Para pagar cuando puedas</label></div>
        <div v-for="e in timeline.open_debts" :key="e.id" class="entry" :class="{ settled: isSettled(e) }">
          <div class="income-head">
            <span class="income-desc">
              {{ e.description }}
              <span v-if="isSettled(e)" class="badge badge-ok">✓ saldado</span>
            </span>
            <span class="income-amount">{{ formatMoney(e.amount, e.currency_id) }}</span>
          </div>
          <p class="muted">pagado {{ formatMoney(e.paid_real, e.currency_id) }} · planificado {{ formatMoney(e.planned_amount, e.currency_id) }}</p>
          <button class="ghost" type="button" @click="openPayments(e)">Pagos</button>
        </div>
      </div>

      <!-- modal de pagos -->
      <div v-if="payEntry" class="modal-overlay" @click.self="closePayments">
        <div class="modal">
          <div class="row">
            <label>Pagos · {{ payEntry.description }}</label>
            <button class="ghost" type="button" @click="closePayments">✕</button>
          </div>

          <p v-if="!payList.length" class="muted">Sin pagos todavía.</p>
          <div v-for="p in payList" :key="p.id" class="item-row" style="cursor: default">
            <template v-if="editPayId === p.id">
              <div style="flex: 1">
                <div class="field-row">
                  <input v-model="editPayDraft.amount" type="text" inputmode="decimal" placeholder="monto" />
                  <input v-if="p.is_planned" v-model="editPayDraft.planned_date" type="date" />
                </div>
                <input v-model="editPayDraft.note" type="text" placeholder="nota" />
                <div class="income-actions">
                  <button class="primary" type="button" @click="saveEditPay(p)">Guardar</button>
                  <button class="ghost" type="button" @click="editPayId = null">Cancelar</button>
                </div>
              </div>
            </template>
            <template v-else>
              <span class="item-desc">
                {{ formatMoney(p.amount, payEntry.currency_id) }}
                <span class="badge">{{ p.is_planned ? 'planificado' : 'real' }}</span>
                <span v-if="p.planned_date" class="muted">{{ p.planned_date }}</span>
                <span v-if="p.note" class="muted">· {{ p.note }}</span>
              </span>
              <span class="item-meta">
                <button class="ghost" type="button" @click="startEditPay(p)">Editar</button>
                <button class="ghost danger" type="button" @click="delPay(p)">Anular</button>
              </span>
            </template>
          </div>

          <div class="row"><label>Registrar pago</label></div>
          <div class="field"><label>Monto</label><input v-model="payForm.amount" type="text" inputmode="decimal" /></div>
          <div class="field"><label>Nota</label><input v-model="payForm.note" type="text" /></div>
          <label class="check"><input v-model="payForm.planned" type="checkbox" /> Planificado (en este plan)</label>
          <div v-if="payForm.planned" class="field"><label>Fecha agendada</label><input v-model="payForm.planned_date" type="date" /></div>
          <button class="primary" type="button" @click="submitPayment">Registrar</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.entry {
  border-top: 1px solid var(--border);
  padding-top: 8px;
  margin-top: 8px;
}
.entry.settled {
  opacity: 0.55;
}
.badge-ok {
  background: var(--positive);
  color: #fff;
  margin-left: 6px;
}
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  z-index: 50;
}
.modal {
  background: var(--card);
  border-radius: var(--radius);
  padding: 16px;
  width: 100%;
  max-width: 380px;
  max-height: 90vh;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.item-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.field-row {
  display: flex;
  gap: 8px;
}
.field-row > input {
  flex: 1;
  min-width: 0;
}
.accent {
  color: var(--positive);
}
.danger {
  color: var(--error);
}
</style>
