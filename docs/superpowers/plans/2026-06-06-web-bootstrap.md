# Web Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (no hay test runner en la web; verificación por `npm run build` + navegador). Steps usan checkbox (`- [ ]`).

**Goal:** La web de pruebas trae `GET /bootstrap` al loguear/registrarse, lo cachea en `localStorage` y lo muestra en el Dashboard.

**Architecture:** `api/index.js` suma `bootstrap()` (GET crudo), `ensureBootstrap()` (cache-first), `getBootstrap()` (lee cache) y borra la cache en `clearSession()`. Login/Register llaman `ensureBootstrap()` tras `saveSession`. El Dashboard lee la cache y la muestra; botón Refrescar fuerza re-fetch.

**Tech Stack:** Vue 3 `<script setup>`, Vite, fetch. Sin test runner → build + verificación manual.

**Spec:** `docs/superpowers/specs/2026-06-06-web-bootstrap-design.md`.

**Git:** rama `feat/web-bootstrap`, commits chicos, **squash-merge** a `main`.

---

## Task 1: API — `bootstrap`, `ensureBootstrap`, `getBootstrap`, limpieza de cache

**Files:** Modify `web/src/api/index.js`

- [ ] **Step 1: Agregar al objeto `api` el método `bootstrap`**

En el objeto `api`, después de `login(...)`, agregar:

```js
  bootstrap() {
    return request('GET', '/bootstrap')
  },
```

- [ ] **Step 2: Agregar helpers de bootstrap + cache (después de `clearSession`)**

```js
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
```

- [ ] **Step 3: Borrar la cache del bootstrap en `clearSession`**

Reemplazar el cuerpo de `clearSession` por:

```js
export function clearSession() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  localStorage.removeItem('bootstrap')
}
```

- [ ] **Step 4: Commit**

```bash
git add web/src/api/index.js
git commit -m "feat(web): api bootstrap + ensureBootstrap (cache-first) + limpieza en logout"
```

---

## Task 2: Login y Register traen el bootstrap tras la sesión

**Files:** Modify `web/src/pages/Login.vue`, `web/src/pages/Register.vue`

- [ ] **Step 1: `Login.vue` — importar y llamar `ensureBootstrap`**

Cambiar el import:

```js
import { api, saveSession, ensureBootstrap } from '../api'
```

En `submit()`, entre `saveSession(data)` y `router.push('/dashboard')`:

```js
    saveSession(data)
    await ensureBootstrap()
    router.push('/dashboard')
```

- [ ] **Step 2: `Register.vue` — igual que Login**

Cambiar el import a `import { api, saveSession, ensureBootstrap } from '../api'` y agregar `await ensureBootstrap()` entre `saveSession(data)` y el `router.push('/dashboard')`.

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/Login.vue web/src/pages/Register.vue
git commit -m "feat(web): traer el bootstrap al loguear y registrarse"
```

---

## Task 3: Dashboard muestra el bootstrap (resumen expandible + Refrescar)

**Files:** Modify `web/src/pages/Dashboard.vue`, `web/src/style.css`

- [ ] **Step 1: Reescribir `Dashboard.vue`**

```vue
<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getUser, clearSession, getBootstrap, ensureBootstrap } from '../api'

const router = useRouter()
const user = getUser()

const bootstrap = ref(getBootstrap())
const error = ref('')
const loading = ref(false)
const open = ref({}) // catálogo -> expandido?

async function load({ force = false } = {}) {
  error.value = ''
  loading.value = true
  try {
    bootstrap.value = await ensureBootstrap({ force })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (!bootstrap.value) load() // fallback: cache vacía (ej. sesión vieja)
})

function toggle(name) {
  open.value[name] = !open.value[name]
}

function itemLabel(item) {
  if (item && typeof item === 'object') {
    const id = item.id ?? item.level ?? item.code
    const name = item.name ?? item.message
    if (id != null && name != null) return `${id} · ${name}`
  }
  return JSON.stringify(item)
}

function logout() {
  clearSession()
  router.push('/login')
}
</script>

<template>
  <div class="screen">
    <div class="content">
      <h1>Dashboard</h1>
      <div class="field">
        <label>ID</label>
        <p class="muted">{{ user?.id }}</p>
      </div>
      <div class="field">
        <label>País</label>
        <p class="muted">{{ user?.country_code }}</p>
      </div>
      <div class="field">
        <label>Nombre</label>
        <p class="muted">{{ user?.display_name || '—' }}</p>
      </div>

      <div class="field">
        <div class="row">
          <label>Bootstrap <span class="muted" v-if="bootstrap">v{{ bootstrap.version }}</span></label>
          <button class="ghost" :disabled="loading" @click="load({ force: true })">
            {{ loading ? 'Cargando…' : 'Refrescar' }}
          </button>
        </div>
        <p v-if="error" class="error">{{ error }}</p>
        <ul v-if="bootstrap" class="catalogs">
          <li v-for="(items, name) in bootstrap.catalogs" :key="name">
            <button class="catalog-head" @click="toggle(name)">
              <span>{{ open[name] ? '▾' : '▸' }} {{ name }}</span>
              <span class="muted">{{ items.length }}</span>
            </button>
            <ul v-if="open[name]" class="catalog-items">
              <li v-for="(item, i) in items" :key="i" class="muted">{{ itemLabel(item) }}</li>
            </ul>
          </li>
        </ul>
      </div>

      <button class="ghost" @click="logout">Cerrar sesión</button>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Agregar estilos al final de `web/src/style.css`**

```css
.row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }

.catalogs { list-style: none; display: flex; flex-direction: column; gap: 0.25rem; }
.catalog-head {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-family: inherit;
  font-size: 0.9rem;
  color: var(--text);
  cursor: pointer;
}
.catalog-head:hover { border-color: var(--accent); }
.catalog-items {
  list-style: none;
  padding: 0.5rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.catalog-items li { font-size: 0.82rem; }
```

- [ ] **Step 3: Build**

Run: `cd web && npm run build`
Expected: compila sin errores.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/Dashboard.vue web/src/style.css
git commit -m "feat(web): Dashboard muestra el bootstrap (resumen expandible + Refrescar)"
```

---

## Task 4: Verificación + doc

**Files:** (sin cambios de código; opcional nota en `web/CLAUDE.md`)

- [ ] **Step 1: Verificación manual en navegador** (backend corriendo + `npm run dev`)

- registrarse/loguearse → el Dashboard lista los 8 catálogos con conteos correctos.
- F5 → sigue mostrando el bootstrap desde la cache (sin re-login, sin nueva request).
- Refrescar → vuelve a traer del backend.
- Cerrar sesión → en DevTools, `localStorage` queda sin la clave `bootstrap`.

- [ ] **Step 2 (opcional): nota en `web/CLAUDE.md`** sobre la cache del bootstrap, si aporta.

---

## Notas de cierre

- Al terminar: la web trae `GET /bootstrap` al loguear, lo cachea, y el Dashboard lo muestra; logout limpia la cache.
- **Cierre:** squash-merge de `feat/web-bootstrap` → un commit `feat: web bootstrap` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** `bootstrap()` + `ensureBootstrap()` cache-first + `getBootstrap()` (T1) ✓; limpieza en `clearSession` (T1) ✓; traer al loguear/registrarse (T2) ✓; Dashboard lee cache + fallback on-mount + Refrescar (force) + resumen expandible (T3) ✓; verificación build + manual (T4) ✓.
- **Placeholders:** ninguno; código completo en cada paso.
- **Consistencia:** `ensureBootstrap({ force })` se usa igual en Login/Register (sin force) y Dashboard (force en Refrescar, sin force en fallback); la clave `'bootstrap'` es la misma en `getBootstrap`/`ensureBootstrap`/`clearSession`; el render usa `bootstrap.catalogs` (las 8 listas) e `itemLabel` tolera cualquier forma de item.
