<script setup>
import { onMounted, ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import { api } from '../api'
import { currencyName, formatMoney } from '../format'

const rows = ref([]) // [{ currency_id, amount }] editable
const error = ref('')
const notice = ref('')

async function load() {
  error.value = ''
  try {
    rows.value = (await api.getBalances()).map((b) => ({ currency_id: b.currency_id, amount: b.amount }))
  } catch (e) {
    error.value = e.message
  }
}

onMounted(load)

async function save() {
  error.value = ''
  notice.value = ''
  const balances = rows.value.map((r) => ({ currency_id: r.currency_id, amount: r.amount }))
  try {
    rows.value = (await api.setBalances({ balances })).map((b) => ({ currency_id: b.currency_id, amount: b.amount }))
    notice.value = 'Billetera guardada.'
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="screen">
    <AppNav />
    <div class="content">
      <h1>Mi billetera</h1>
      <p class="muted">Cuánto efectivo tenés ahora en cada moneda.</p>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="notice" class="muted">{{ notice }}</p>

      <p v-if="!rows.length" class="muted">No hay monedas disponibles para tu país.</p>

      <div class="income-form">
        <div v-for="r in rows" :key="r.currency_id" class="field">
          <label>{{ currencyName(r.currency_id) }}</label>
          <input v-model="r.amount" type="text" inputmode="decimal" />
          <span class="muted">{{ formatMoney(r.amount, r.currency_id) }}</span>
        </div>
        <button v-if="rows.length" class="primary" type="button" @click="save">Guardar</button>
      </div>
    </div>
  </div>
</template>
