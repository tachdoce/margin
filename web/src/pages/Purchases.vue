<script setup>
import { computed, onMounted, ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import { api, getBootstrap, ensureBootstrap } from '../api'
import { formatMoney } from '../format'

const purchases = ref([])
const cards = ref([])
const catalogs = ref({ purchase_categories: [], currencies: [], institutions: [], credit_card_networks: [] })
const error = ref('')
const loading = ref(false)
const editingId = ref(null) // null = modo crear

function today() {
  return new Date().toISOString().slice(0, 10)
}

function blankForm() {
  return {
    medio: 'efectivo', // 'efectivo' | 'tarjeta'
    credit_card_id: '',
    category_id: '',
    total_installments: '',
    description: '',
    purchase_date: today(),
    currency_id: '',
    amount: '',
  }
}

const form = ref(blankForm())

// solo tarjetas activas (el backend rechaza las borradas)
const activeCards = computed(() => cards.value.filter((c) => !c.deleted_at))

// solo monedas habilitadas para tarjeta
const payableCurrencies = computed(() =>
  (catalogs.value.currencies || []).filter((c) => c.allowed_in_credit_card),
)

function defaultCurrency() {
  const list = payableCurrencies.value
  return (list.find((c) => c.is_legal_tender) ?? list[0])?.id ?? ''
}

function currencyName(id) {
  return catalogs.value.currencies?.find((c) => c.id === id)?.name ?? `#${id}`
}

function categoryName(id) {
  if (id == null) return 'Sin categoría'
  const c = catalogs.value.purchase_categories?.find((x) => x.id === id)
  return c ? `${c.emoji} ${c.name}` : `#${id}`
}

function cardLabel(id) {
  const card = cards.value.find((c) => c.id === id)
  if (!card) return 'Tarjeta'
  const inst = catalogs.value.institutions?.find((i) => i.id === card.institution_id)?.name ?? '—'
  const net = catalogs.value.credit_card_networks?.find((n) => n.id === card.card_network_id)?.name ?? '—'
  return `${inst} ${net}`
}

function medioLabel(p) {
  return p.credit_card_id ? cardLabel(p.credit_card_id) : 'Efectivo'
}

function setMedio(m) {
  form.value.medio = m
  if (m === 'efectivo') form.value.total_installments = ''
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

async function loadCards() {
  try {
    cards.value = (await api.listCreditCards()).credit_cards
  } catch {
    cards.value = []
  }
}

async function loadPurchases() {
  error.value = ''
  loading.value = true
  try {
    purchases.value = (await api.listPurchases()).purchases
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadCatalogs()
  await loadCards()
  await loadPurchases()
})

function startCreate() {
  editingId.value = null
  form.value = blankForm()
  form.value.currency_id = defaultCurrency()
  error.value = ''
}

function startEdit(p) {
  editingId.value = p.id
  form.value = {
    medio: p.credit_card_id ? 'tarjeta' : 'efectivo',
    credit_card_id: p.credit_card_id ?? '',
    category_id: p.category_id ?? '',
    total_installments: p.total_installments ?? '',
    description: p.description ?? '',
    purchase_date: p.purchase_date,
    currency_id: p.currency_id,
    amount: p.amount,
  }
  error.value = ''
}

function buildBody() {
  const f = form.value
  return {
    credit_card_id: f.medio === 'tarjeta' ? f.credit_card_id || null : null,
    category_id: f.category_id === '' ? null : Number(f.category_id),
    total_installments: f.medio === 'tarjeta' && f.total_installments !== '' ? Number(f.total_installments) : null,
    description: f.description,
    purchase_date: f.purchase_date,
    amount: String(f.amount),
    currency_id: Number(f.currency_id),
  }
}

async function submit() {
  error.value = ''
  try {
    if (editingId.value) {
      await api.updatePurchase(editingId.value, buildBody())
    } else {
      await api.createPurchase(buildBody())
    }
    startCreate()
    await loadPurchases()
  } catch (e) {
    error.value = e.message
  }
}

async function remove(p) {
  error.value = ''
  try {
    await api.deletePurchase(p.id)
    if (editingId.value === p.id) startCreate()
    await loadPurchases()
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <AppNav />
    <div class="content">
      <h1>Compras</h1>

      <p v-if="error" class="error">{{ error }}</p>

      <!-- Form crear / editar -->
      <form class="income-form" @submit.prevent="submit">
        <div class="row">
          <label>{{ editingId ? 'Editar compra' : 'Nueva compra' }}</label>
          <button v-if="editingId" type="button" class="ghost" @click="startCreate">Cancelar</button>
        </div>

        <div class="seg">
          <button
            type="button"
            class="seg-btn"
            :class="{ 'seg-active': form.medio === 'efectivo' }"
            @click="setMedio('efectivo')"
          >
            Efectivo
          </button>
          <button
            type="button"
            class="seg-btn"
            :class="{ 'seg-active': form.medio === 'tarjeta' }"
            @click="setMedio('tarjeta')"
          >
            Tarjeta
          </button>
        </div>

        <div v-if="form.medio === 'tarjeta'" class="field">
          <label>Tarjeta</label>
          <select v-model="form.credit_card_id">
            <option value="" disabled>Elegí una tarjeta</option>
            <option v-for="c in activeCards" :key="c.id" :value="c.id">{{ cardLabel(c.id) }}</option>
          </select>
          <p v-if="!activeCards.length" class="muted">No tenés tarjetas activas.</p>
        </div>

        <div v-if="form.medio === 'tarjeta'" class="field">
          <label>Cuotas</label>
          <input v-model="form.total_installments" type="number" min="1" placeholder="1" />
        </div>

        <div class="field">
          <label>Categoría</label>
          <select v-model="form.category_id">
            <option value="">Sin categoría</option>
            <option v-for="c in catalogs.purchase_categories" :key="c.id" :value="c.id">
              {{ c.emoji }} {{ c.name }}
            </option>
          </select>
        </div>

        <div class="field">
          <label>Descripción (opcional)</label>
          <input v-model="form.description" type="text" placeholder="Almuerzo" />
        </div>

        <div class="field">
          <label>Fecha</label>
          <input v-model="form.purchase_date" type="date" />
        </div>

        <div class="field">
          <label>Moneda</label>
          <select v-model="form.currency_id">
            <option value="" disabled>Elegí una moneda</option>
            <option v-for="c in payableCurrencies" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>

        <div class="field">
          <label>Monto</label>
          <input v-model="form.amount" type="text" inputmode="decimal" placeholder="450.00" />
        </div>

        <button class="primary" type="submit">{{ editingId ? 'Guardar cambios' : 'Crear' }}</button>
      </form>

      <!-- Lista -->
      <div class="row">
        <label>Mis compras</label>
        <button class="ghost" :disabled="loading" @click="loadPurchases">
          {{ loading ? 'Cargando…' : 'Refrescar' }}
        </button>
      </div>

      <p v-if="!purchases.length" class="muted">Todavía no cargaste compras.</p>

      <div v-for="p in purchases" :key="p.id" class="income-card">
        <div class="income-head">
          <span class="income-desc">{{ p.description || categoryName(p.category_id) }}</span>
          <span class="income-amount">{{ formatMoney(p.amount, p.currency_id) }}</span>
        </div>
        <p class="muted">
          {{ categoryName(p.category_id) }} · {{ medioLabel(p) }} · {{ p.purchase_date }}
          <span v-if="p.total_installments > 1"> · {{ p.total_installments }}x cuotas</span>
        </p>
        <div class="income-actions">
          <button class="ghost" @click="startEdit(p)">Editar</button>
          <button class="ghost danger" @click="remove(p)">Borrar</button>
        </div>
      </div>
    </div>
  </div>
</template>
