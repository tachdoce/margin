<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import { api, getBootstrap, ensureBootstrap } from '../api'

const catalogs = ref({
  institutions: [],
  credit_card_networks: [],
  credit_card_item_types: [],
  currencies: [],
  review_finding_codes: [],
})
const error = ref('')
const notice = ref('')

// --- staging ---
const staging = ref(null) // { ...madre, items: [...] } | null
const madreForm = reactive(blankMadre())
const itemModal = ref(null) // ítem en edición (modal) | null

const EXAMPLE = JSON.stringify(
  {
    general_data: {
      issuer: 'Scotiabank',
      card_network: 'Amex',
      closing_date: '2026-05-13',
      due_date: '2026-05-25',
      current_limit: 180000.0,
    },
    payment_summary: {
      total_local: 7991.28,
      total_usd: 65.35,
      minimum_payment_local: 600.0,
      minimum_payment_usd: 0.0,
    },
    charges: [
      { date: '2026-02-02', description: 'SPORTLINE PUNTA', amount: 1997.5, currency: 'Peso', current_installment: 3, total_installments: 4 },
      { date: '2026-04-29', description: 'GOOGLE *COM PULSO PULS', amount: 69.99, currency: 'Dólar' },
    ],
    payments: [],
    others: [],
    annual_effective_rates: {
      vat_excluded: false,
      financing_rate_local_this_month: 69.98,
      overdue_rate_local_this_month: 81.27,
      financing_rate_usd_this_month: 13.5,
      overdue_rate_usd_this_month: 15.68,
      financing_rate_local_next_month: 70.09,
      overdue_rate_local_next_month: 81.39,
      financing_rate_usd_next_month: 14.61,
      overdue_rate_usd_next_month: 16.97,
    },
  },
  null,
  2,
)
const rawPayload = ref('')

function useExample() {
  rawPayload.value = EXAMPLE
}

// --- tarjetas definitivas ---
const cards = ref([])
const cardEdits = reactive({}) // cardId -> form de edición (o ausente)
const history = reactive({}) // cardId -> { statements: [...], items: { statementId: [...] } }
const promoteResult = ref(null)

function blankMadre() {
  return {
    institution_id: '',
    card_network_id: '',
    closing_date: '',
    due_date: '',
    current_limit: '',
    total_local: '',
    total_usd: '',
    minimum_payment_local: '',
    minimum_payment_usd: '',
    financing_rate_local: '',
    overdue_rate_local: '',
    financing_rate_usd: '',
    overdue_rate_usd: '',
    rates_add_vat: true,
  }
}

// --- resolvers desde catálogos ---
function institutionName(id) {
  return catalogs.value.institutions?.find((i) => i.id === id)?.name ?? (id == null ? '—' : `#${id}`)
}
function networkName(id) {
  return catalogs.value.credit_card_networks?.find((n) => n.id === id)?.name ?? (id == null ? '—' : `#${id}`)
}
function currencyName(id) {
  return catalogs.value.currencies?.find((c) => c.id === id)?.name ?? (id == null ? '—' : `#${id}`)
}
function itemTypeName(id) {
  return catalogs.value.credit_card_item_types?.find((t) => t.id === id)?.name ?? (id == null ? '—' : `#${id}`)
}
function findingMessage(code) {
  return catalogs.value.review_finding_codes?.find((c) => c.code === code)?.message ?? code
}
const cardCurrencies = computed(() =>
  (catalogs.value.currencies || []).filter((c) => c.allowed_in_credit_card),
)

// --- helpers de conversión form -> body ---
function numOrNull(v) {
  return v === '' || v === null ? null : String(v)
}
function intOrNull(v) {
  return v === '' || v === null ? null : Number(v)
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

async function loadStaging() {
  try {
    const data = await api.getStaging()
    staging.value = data
    Object.assign(madreForm, {
      institution_id: data.institution_id ?? '',
      card_network_id: data.card_network_id ?? '',
      closing_date: data.closing_date ?? '',
      due_date: data.due_date ?? '',
      current_limit: data.current_limit ?? '',
      total_local: data.total_local ?? '',
      total_usd: data.total_usd ?? '',
      minimum_payment_local: data.minimum_payment_local ?? '',
      minimum_payment_usd: data.minimum_payment_usd ?? '',
      financing_rate_local: data.financing_rate_local ?? '',
      overdue_rate_local: data.overdue_rate_local ?? '',
      financing_rate_usd: data.financing_rate_usd ?? '',
      overdue_rate_usd: data.overdue_rate_usd ?? '',
      rates_add_vat: data.rates_add_vat ?? true,
    })
  } catch (e) {
    if (e.code === 'not_found') {
      staging.value = null
    } else {
      error.value = e.message
    }
  }
}

async function loadCards() {
  try {
    cards.value = (await api.listCreditCards()).credit_cards
  } catch (e) {
    error.value = e.message
  }
}

onMounted(async () => {
  await loadCatalogs()
  await loadStaging()
  await loadCards()
})

// --- acciones staging ---
async function loadStatement() {
  error.value = ''
  notice.value = ''
  let body
  try {
    body = JSON.parse(rawPayload.value)
  } catch {
    error.value = 'El JSON no es válido.'
    return
  }
  try {
    await api.loadStatement(body)
    notice.value = 'Resumen cargado en staging.'
    await loadStaging()
  } catch (e) {
    error.value = e.message
  }
}

async function saveMadre() {
  error.value = ''
  const body = {
    institution_id: intOrNull(madreForm.institution_id),
    card_network_id: intOrNull(madreForm.card_network_id),
    closing_date: madreForm.closing_date || null,
    due_date: madreForm.due_date || null,
    current_limit: numOrNull(madreForm.current_limit),
    total_local: numOrNull(madreForm.total_local),
    total_usd: numOrNull(madreForm.total_usd),
    minimum_payment_local: numOrNull(madreForm.minimum_payment_local),
    minimum_payment_usd: numOrNull(madreForm.minimum_payment_usd),
    financing_rate_local: numOrNull(madreForm.financing_rate_local),
    overdue_rate_local: numOrNull(madreForm.overdue_rate_local),
    financing_rate_usd: numOrNull(madreForm.financing_rate_usd),
    overdue_rate_usd: numOrNull(madreForm.overdue_rate_usd),
    rates_add_vat: madreForm.rates_add_vat,
  }
  try {
    await api.updateStagingMadre(body)
    notice.value = 'Madre guardada.'
    await loadStaging()
  } catch (e) {
    error.value = e.message
  }
}

function openItem(it) {
  itemModal.value = {
    id: it.id,
    charge_date: it.charge_date ?? '',
    description: it.description ?? '',
    amount: it.amount ?? '',
    currency_id: it.currency_id ?? '',
    item_type_id: it.item_type_id ?? '',
    current_installment: it.current_installment ?? '',
    total_installments: it.total_installments ?? '',
    missing_fields: it.missing_fields,
  }
}

function closeItem() {
  itemModal.value = null
}

async function saveItem() {
  error.value = ''
  const f = itemModal.value
  const body = {
    charge_date: f.charge_date || null,
    description: f.description || null,
    amount: numOrNull(f.amount),
    currency_id: intOrNull(f.currency_id),
    item_type_id: intOrNull(f.item_type_id),
    current_installment: intOrNull(f.current_installment),
    total_installments: intOrNull(f.total_installments),
  }
  try {
    await api.updateStagingItem(f.id, body)
    notice.value = 'Ítem guardado.'
    closeItem()
    await loadStaging()
  } catch (e) {
    error.value = e.message
  }
}

async function ackStaging() {
  error.value = ''
  try {
    await api.acknowledgeStaging()
    await loadStaging()
  } catch (e) {
    error.value = e.message
  }
}

async function discardStaging() {
  error.value = ''
  try {
    await api.discardStaging()
    notice.value = 'Staging descartado.'
    await loadStaging()
  } catch (e) {
    error.value = e.message
  }
}

async function promote() {
  error.value = ''
  promoteResult.value = null
  try {
    promoteResult.value = await api.promoteStaging()
    notice.value = 'Promovido.'
    await loadStaging()
    await loadCards()
  } catch (e) {
    error.value = e.message
  }
}

// --- acciones tarjetas ---
function startEditCard(card) {
  cardEdits[card.id] = {
    institution_id: card.institution_id,
    card_network_id: card.card_network_id,
    closing_day: card.closing_day,
    due_day: card.due_day,
  }
}
function cancelEditCard(card) {
  delete cardEdits[card.id]
}
async function saveCard(card) {
  error.value = ''
  const f = cardEdits[card.id]
  try {
    await api.updateCreditCard(card.id, {
      institution_id: Number(f.institution_id),
      card_network_id: Number(f.card_network_id),
      closing_day: Number(f.closing_day),
      due_day: Number(f.due_day),
    })
    delete cardEdits[card.id]
    await loadCards()
  } catch (e) {
    error.value = e.message
  }
}
async function ackCard(card) {
  error.value = ''
  try {
    await api.acknowledgeCreditCard(card.id)
    await loadCards()
  } catch (e) {
    error.value = e.message
  }
}
async function delCard(card) {
  error.value = ''
  try {
    await api.deleteCreditCard(card.id)
    await loadCards()
  } catch (e) {
    error.value = e.message
  }
}
async function reactivateCard(card) {
  error.value = ''
  try {
    await api.reactivateCreditCard(card.id)
    await loadCards()
  } catch (e) {
    error.value = e.message
  }
}

// --- historial ---
async function toggleStatements(card) {
  if (history[card.id]) {
    delete history[card.id]
    return
  }
  error.value = ''
  try {
    const sts = (await api.listCardStatements(card.id)).statements
    history[card.id] = { statements: sts, items: {} }
  } catch (e) {
    error.value = e.message
  }
}
async function toggleItems(card, st) {
  const h = history[card.id]
  if (h.items[st.id]) {
    delete h.items[st.id]
    return
  }
  error.value = ''
  try {
    h.items[st.id] = (await api.listCardStatementItems(card.id, st.id)).items
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <AppNav />
    <div class="content">
      <h1>Tarjetas de crédito</h1>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="notice" class="muted">{{ notice }}</p>

      <!-- ZONA A: cargar resumen -->
      <div class="income-form">
        <div class="row"><label>Cargar resumen (pegá el JSON del estado de cuenta)</label></div>
        <textarea
          v-model="rawPayload"
          rows="10"
          class="mono"
          placeholder="Pegá acá el JSON del estado de cuenta (general_data, payment_summary, charges, annual_effective_rates)"
        ></textarea>
        <div class="income-actions">
          <button class="primary" type="button" @click="loadStatement">Cargar a staging</button>
          <button class="ghost" type="button" @click="useExample">Usar ejemplo</button>
        </div>
      </div>

      <!-- ZONA A: staging actual -->
      <div v-if="staging" class="income-form">
        <div class="row">
          <label>Staging en revisión</label>
          <span class="badge" :class="{ 'badge-ok': staging.is_ready }">
            {{ staging.is_ready ? 'listo' : 'en revisión' }}
          </span>
        </div>

        <p v-if="staging.review_findings.length" class="error">
          ⚠ {{ staging.review_findings.map(findingMessage).join(' · ') }}
        </p>

        <!-- madre -->
        <div class="field-row">
          <div class="field">
            <label>Emisor</label>
            <select v-model="madreForm.institution_id">
              <option value="">Sin resolver</option>
              <option v-for="i in catalogs.institutions" :key="i.id" :value="i.id">{{ i.name }}</option>
            </select>
          </div>
          <div class="field">
            <label>Red</label>
            <select v-model="madreForm.card_network_id">
              <option value="">Sin resolver</option>
              <option v-for="n in catalogs.credit_card_networks" :key="n.id" :value="n.id">{{ n.name }}</option>
            </select>
          </div>
        </div>
        <div class="field-row">
          <div class="field"><label>Cierre</label><input v-model="madreForm.closing_date" type="date" /></div>
          <div class="field"><label>Vencimiento</label><input v-model="madreForm.due_date" type="date" /></div>
        </div>
        <div class="field"><label>Límite</label><input v-model="madreForm.current_limit" type="text" inputmode="decimal" /></div>
        <div class="field-row">
          <div class="field"><label>Total local</label><input v-model="madreForm.total_local" type="text" inputmode="decimal" /></div>
          <div class="field"><label>Total USD</label><input v-model="madreForm.total_usd" type="text" inputmode="decimal" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Mínimo local</label><input v-model="madreForm.minimum_payment_local" type="text" inputmode="decimal" /></div>
          <div class="field"><label>Mínimo USD</label><input v-model="madreForm.minimum_payment_usd" type="text" inputmode="decimal" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Financiación local (opc.)</label><input v-model="madreForm.financing_rate_local" type="text" inputmode="decimal" /></div>
          <div class="field"><label>Financiación USD (opc.)</label><input v-model="madreForm.financing_rate_usd" type="text" inputmode="decimal" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Mora local (opc.)</label><input v-model="madreForm.overdue_rate_local" type="text" inputmode="decimal" /></div>
          <div class="field"><label>Mora USD (opc.)</label><input v-model="madreForm.overdue_rate_usd" type="text" inputmode="decimal" /></div>
        </div>
        <label class="check"><input v-model="madreForm.rates_add_vat" type="checkbox" /> Las tasas llevan IVA</label>

        <div class="income-actions">
          <button class="primary" type="button" @click="saveMadre">Guardar madre</button>
          <button v-if="staging.review_findings.length" class="ghost accent" type="button" @click="ackStaging">Reconocer</button>
          <button class="ghost danger" type="button" @click="discardStaging">Descartar</button>
          <button class="ghost" type="button" @click="promote">Promover</button>
        </div>

        <p v-if="promoteResult" class="muted">
          Promovido → tarjeta {{ promoteResult.credit_card_id.slice(0, 8) }} ·
          {{ promoteResult.is_ready ? 'lista' : 'con observaciones' }}
          <span v-if="promoteResult.review_findings.length">
            ({{ promoteResult.review_findings.map(findingMessage).join(' · ') }})
          </span>
        </p>

        <!-- ítems: lista; clic abre el modal de edición -->
        <div class="row"><label>Ítems del resumen ({{ staging.items.length }})</label></div>
        <ul class="item-list">
          <li v-for="it in staging.items" :key="it.id" class="item-row" @click="openItem(it)">
            <span class="item-desc">{{ it.description || '(sin descripción)' }}</span>
            <span class="item-meta">
              {{ it.amount ?? '—' }} {{ it.currency_id ? currencyName(it.currency_id) : '' }}
              <span v-if="it.missing_fields.length" class="badge">incompleto</span>
            </span>
          </li>
        </ul>
      </div>

      <p v-else class="muted">No hay ningún resumen en staging. Cargá uno arriba.</p>

      <!-- ZONA B: tarjetas -->
      <div class="row">
        <label>Mis tarjetas</label>
        <button class="ghost" type="button" @click="loadCards">Refrescar</button>
      </div>
      <p v-if="!cards.length" class="muted">Todavía no tenés tarjetas (promové un resumen).</p>

      <div v-for="card in cards" :key="card.id" class="income-card" :class="{ deleted: card.is_deleted }">
        <div class="income-head">
          <span class="income-desc">
            {{ institutionName(card.institution_id) }} · {{ networkName(card.card_network_id) }}
            <span v-if="card.is_deleted" class="badge">borrada</span>
            <span v-else-if="!card.is_ready" class="badge">en revisión</span>
          </span>
          <span class="income-amount">cierra {{ card.closing_day }} · vence {{ card.due_day }}</span>
        </div>
        <p class="muted">
          Límite {{ card.current_limit }} · fin {{ card.financing_rate_local }}/{{ card.financing_rate_usd }} ·
          mora {{ card.overdue_rate_local }}/{{ card.overdue_rate_usd }} · IVA {{ card.rates_add_vat ? 'sí' : 'no' }}
        </p>
        <p v-if="card.review_findings.length" class="error">
          ⚠ {{ card.review_findings.map(findingMessage).join(' · ') }}
        </p>

        <!-- form de edición inline -->
        <div v-if="cardEdits[card.id]" class="income-form">
          <div class="field">
            <label>Emisor</label>
            <select v-model="cardEdits[card.id].institution_id">
              <option v-for="i in catalogs.institutions" :key="i.id" :value="i.id">{{ i.name }}</option>
            </select>
          </div>
          <div class="field">
            <label>Red</label>
            <select v-model="cardEdits[card.id].card_network_id">
              <option v-for="n in catalogs.credit_card_networks" :key="n.id" :value="n.id">{{ n.name }}</option>
            </select>
          </div>
          <div class="field"><label>Día de cierre</label><input v-model="cardEdits[card.id].closing_day" type="number" min="1" max="31" /></div>
          <div class="field"><label>Día de vencimiento</label><input v-model="cardEdits[card.id].due_day" type="number" min="1" max="31" /></div>
          <div class="income-actions">
            <button class="primary" type="button" @click="saveCard(card)">Guardar</button>
            <button class="ghost" type="button" @click="cancelEditCard(card)">Cancelar</button>
          </div>
        </div>

        <div class="income-actions">
          <button v-if="!card.is_deleted" class="ghost" type="button" @click="startEditCard(card)">Editar</button>
          <button v-if="!card.is_deleted && card.review_findings.length" class="ghost accent" type="button" @click="ackCard(card)">Reconocer</button>
          <button v-if="!card.is_deleted" class="ghost danger" type="button" @click="delCard(card)">Borrar</button>
          <button v-if="card.is_deleted" class="ghost accent" type="button" @click="reactivateCard(card)">Reactivar</button>
          <button class="ghost" type="button" @click="toggleStatements(card)">
            {{ history[card.id] ? 'Ocultar historial' : 'Ver historial' }}
          </button>
        </div>

        <!-- historial -->
        <div v-if="history[card.id]" class="history">
          <p v-if="!history[card.id].statements.length" class="muted">Sin resúmenes.</p>
          <div v-for="st in history[card.id].statements" :key="st.id" class="history-st">
            <div class="income-head">
              <span class="income-desc">{{ st.issue_month }}/{{ st.issue_year }} · vence {{ st.due_date }}</span>
              <span class="income-amount">{{ st.total_local }} / {{ st.total_usd }}</span>
            </div>
            <button class="ghost" type="button" @click="toggleItems(card, st)">
              {{ history[card.id].items[st.id] ? 'Ocultar cargos' : 'Ver cargos' }}
            </button>
            <ul v-if="history[card.id].items[st.id]">
              <li v-for="it in history[card.id].items[st.id]" :key="it.id" class="muted">
                {{ it.charge_date }} · {{ it.description }} · {{ it.amount }} {{ currencyName(it.currency_id) }}
                <span v-if="it.total_installments">(cuota {{ it.current_installment }}/{{ it.total_installments }})</span>
                · {{ itemTypeName(it.item_type_id) }}
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- modal de edición de ítem -->
      <div v-if="itemModal" class="modal-overlay" @click.self="closeItem">
        <div class="modal">
          <div class="row">
            <label>Editar ítem</label>
            <button class="ghost" type="button" @click="closeItem">✕</button>
          </div>
          <p v-if="itemModal.missing_fields.length" class="error">Falta: {{ itemModal.missing_fields.join(', ') }}</p>
          <div class="field"><label>Fecha</label><input v-model="itemModal.charge_date" type="date" /></div>
          <div class="field"><label>Descripción</label><input v-model="itemModal.description" type="text" /></div>
          <div class="field"><label>Monto</label><input v-model="itemModal.amount" type="text" inputmode="decimal" /></div>
          <div class="field">
            <label>Moneda</label>
            <select v-model="itemModal.currency_id">
              <option value="">Sin resolver</option>
              <option v-for="c in cardCurrencies" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </div>
          <div class="field">
            <label>Tipo</label>
            <select v-model="itemModal.item_type_id">
              <option value="">Sin asignar</option>
              <option v-for="t in catalogs.credit_card_item_types" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
          </div>
          <div class="field-row">
            <div class="field"><label>Cuota actual</label><input v-model="itemModal.current_installment" type="number" min="1" /></div>
            <div class="field"><label>Cuotas totales</label><input v-model="itemModal.total_installments" type="number" min="1" /></div>
          </div>
          <div class="income-actions">
            <button class="primary" type="button" @click="saveItem">Guardar</button>
            <button class="ghost" type="button" @click="closeItem">Cancelar</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: monospace;
  font-size: 12px;
  width: 100%;
}
.badge-ok {
  background: var(--positive);
}
.history {
  margin-top: 8px;
  padding-left: 12px;
  border-left: 2px solid var(--border);
}
.field-row {
  display: flex;
  gap: 8px;
}
.field-row > .field {
  flex: 1;
  min-width: 0;
}
.item-list {
  list-style: none;
  padding: 0;
  margin: 8px 0;
}
.item-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  padding: 10px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 6px;
  cursor: pointer;
}
.item-row:hover {
  border-color: var(--accent);
}
.item-desc {
  font-weight: 500;
}
.item-meta {
  color: var(--text-secondary);
  font-size: 0.9rem;
  white-space: nowrap;
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
  max-width: 360px;
  max-height: 90vh;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.history-st {
  margin-bottom: 8px;
}
</style>
