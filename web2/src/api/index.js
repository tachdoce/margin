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
  // --- ingresos ---
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
  // --- deudas ---
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
  // --- planes ---
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
  runPlanning(id) {
    return request('POST', `/plans/${id}/planning`)
  },
  clearPlanning(id) {
    return request('DELETE', `/plans/${id}/planning`)
  },
  // --- flujo de caja: timeline + pagos ---
  getTimeline(planId) {
    return request('GET', `/cash-flow-entries?plan_id=${planId}`)
  },
  listPayments(entryId, planId) {
    return request('GET', `/cash-flow-entries/${entryId}/payments?plan_id=${planId}`)
  },
  createPayment(entryId, body) {
    return request('POST', `/cash-flow-entries/${entryId}/payments`, body)
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
