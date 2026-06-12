const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(method, path, body) {
  const token = localStorage.getItem('token')
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 204) return null
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    // Envelope de error del backend: {code, message, field?} o {code, message, errors:[]}
    const err = new Error(data.message || 'Error inesperado')
    err.code = data.code
    err.field = data.field
    err.errors = data.errors
    throw err
  }
  return data
}

export const api = {
  register(email, password, displayName) {
    const body = { email, password }
    if (displayName) body.display_name = displayName
    return request('POST', '/auth/register', body)
  },
  login(email, password) {
    return request('POST', '/auth/login', { email, password })
  },
  bootstrap() {
    return request('GET', '/bootstrap')
  },
  listIncomes() {
    return request('GET', '/incomes')
  },
  createIncome(body) {
    return request('POST', '/incomes', body)
  },
  updateIncome(id, body) {
    return request('PATCH', `/incomes/${id}`, body)
  },
  deleteIncome(id) {
    return request('DELETE', `/incomes/${id}`)
  },
  reactivateIncome(id) {
    return request('POST', `/incomes/${id}/reactivate`)
  },
  listPlans() {
    return request('GET', '/plans')
  },
  createPlan(body) {
    return request('POST', '/plans', body)
  },
  updatePlan(id, body) {
    return request('PATCH', `/plans/${id}`, body)
  },
  deletePlan(id) {
    return request('DELETE', `/plans/${id}`)
  },
  selectPlan(id) {
    return request('POST', `/plans/${id}/select`)
  },
  copyPlan(id, body) {
    return request('POST', `/plans/${id}/copy`, body)
  },
  runPlanning(id) {
    return request('POST', `/plans/${id}/planning`)
  },
  clearPlanning(id) {
    return request('DELETE', `/plans/${id}/planning`)
  },
  listMovements(planId) {
    return request('GET', `/plans/${planId}/movements`)
  },
  createMovement(planId, body) {
    return request('POST', `/plans/${planId}/movements`, body)
  },
  updateMovement(planId, id, body) {
    return request('PATCH', `/plans/${planId}/movements/${id}`, body)
  },
  deleteMovement(planId, id) {
    return request('DELETE', `/plans/${planId}/movements/${id}`)
  },
  listExpenses() {
    return request('GET', '/expenses')
  },
  createExpense(body) {
    return request('POST', '/expenses', body)
  },
  updateExpense(id, body) {
    return request('PATCH', `/expenses/${id}`, body)
  },
  deleteExpense(id) {
    return request('DELETE', `/obligations/${id}`)
  },
  listDebts() {
    return request('GET', '/debts')
  },
  createDebt(body) {
    return request('POST', '/debts', body)
  },
  updateDebt(id, body) {
    return request('PATCH', `/debts/${id}`, body)
  },
  deleteDebt(id) {
    return request('DELETE', `/obligations/${id}`)
  },
  acknowledgeObligation(id) {
    return request('POST', `/obligations/${id}/acknowledge`)
  },
  // --- tarjetas de crédito: staging ---
  getStaging() {
    return request('GET', '/credit-card-statements')
  },
  loadStatement(body) {
    return request('POST', '/credit-card-statements', body)
  },
  updateStagingMadre(body) {
    return request('PUT', '/credit-card-statements', body)
  },
  updateStagingItem(itemId, body) {
    return request('PUT', `/credit-card-statements/items/${itemId}`, body)
  },
  acknowledgeStaging() {
    return request('POST', '/credit-card-statements/acknowledge')
  },
  discardStaging() {
    return request('DELETE', '/credit-card-statements')
  },
  promoteStaging() {
    return request('POST', '/credit-card-statements/promote')
  },
  // --- tarjetas de crédito: definitivas ---
  listCreditCards() {
    return request('GET', '/credit-cards')
  },
  updateCreditCard(id, body) {
    return request('PATCH', `/credit-cards/${id}`, body)
  },
  acknowledgeCreditCard(id) {
    return request('POST', `/credit-cards/${id}/acknowledge`)
  },
  deleteCreditCard(id) {
    return request('DELETE', `/credit-cards/${id}`)
  },
  reactivateCreditCard(id) {
    return request('POST', `/credit-cards/${id}/reactivate`)
  },
  listCardStatements(cardId) {
    return request('GET', `/credit-cards/${cardId}/statements`)
  },
  listCardStatementItems(cardId, statementId) {
    return request('GET', `/credit-cards/${cardId}/statements/${statementId}/items`)
  },
  // --- flujo de caja: timeline + pagos ---
  getTimeline(planId) {
    return request('GET', `/cash-flow-entries?plan_id=${planId}`)
  },
  updateEntry(entryId, body) {
    return request('PATCH', `/cash-flow-entries/${entryId}`, body)
  },
  listPayments(entryId, planId) {
    return request('GET', `/cash-flow-entries/${entryId}/payments?plan_id=${planId}`)
  },
  createPayment(entryId, body) {
    return request('POST', `/cash-flow-entries/${entryId}/payments`, body)
  },
  updatePayment(entryId, paymentId, body) {
    return request('PATCH', `/cash-flow-entries/${entryId}/payments/${paymentId}`, body)
  },
  deletePayment(entryId, paymentId) {
    return request('DELETE', `/cash-flow-entries/${entryId}/payments/${paymentId}`)
  },
  // --- billetera: efectivo por moneda ---
  getBalances() {
    return request('GET', '/cash-balances')
  },
  setBalances(body) {
    return request('PUT', '/cash-balances', body)
  },
  // --- compras (tarjeta o efectivo) con categoría ---
  listPurchases() {
    return request('GET', '/purchases')
  },
  createPurchase(body) {
    return request('POST', '/purchases', body)
  },
  updatePurchase(id, body) {
    return request('PATCH', `/purchases/${id}`, body)
  },
  deletePurchase(id) {
    return request('DELETE', `/purchases/${id}`)
  },
}

export function saveSession({ user, token }) {
  localStorage.setItem('token', token)
  localStorage.setItem('user', JSON.stringify(user))
}

export function getUser() {
  const raw = localStorage.getItem('user')
  return raw ? JSON.parse(raw) : null
}

export function clearSession() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  localStorage.removeItem('bootstrap')
}

export function isAuthenticated() {
  return !!localStorage.getItem('token')
}

const BOOTSTRAP_KEY = 'bootstrap'

export function getBootstrap() {
  const raw = localStorage.getItem(BOOTSTRAP_KEY)
  return raw ? JSON.parse(raw) : null
}

// Cache-first: si ya está cacheado lo devuelve; si no (o force=true) lo trae y cachea.
export async function ensureBootstrap({ force = false } = {}) {
  if (!force) {
    const cached = getBootstrap()
    if (cached) return cached
  }
  const data = await api.bootstrap()
  localStorage.setItem(BOOTSTRAP_KEY, JSON.stringify(data))
  return data
}
