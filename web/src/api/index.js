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
}

export function isAuthenticated() {
  return !!localStorage.getItem('token')
}
