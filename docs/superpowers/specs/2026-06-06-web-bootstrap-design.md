# Web: consumir `GET /bootstrap` — Diseño

> La web de pruebas trae el bootstrap apenas hay sesión, lo cachea (como hará la app móvil real:
> el bootstrap es un diccionario que el front cachea) y lo muestra en el Dashboard. Banco de pruebas:
> el objetivo es ejercitar el endpoint, no diseñar UI.

- **Fecha:** 2026-06-06
- **Estado:** aprobado para implementar
- **Depende de:** `GET /bootstrap` (ya en `main`) y la auth de la web (`api.login/register`, sesión en localStorage).
- **Cierre:** rama `feat/web-bootstrap`, **squash-merge** a `main`.

---

## 1. Alcance

- `src/api/index.js`: método `bootstrap()` (GET `/bootstrap`), `ensureBootstrap()` (cache-first),
  `getBootstrap()` (lee cache), y borrar la cache en `clearSession()`.
- `Login.vue` y `Register.vue`: tras `saveSession(...)` y **antes** de redirigir, llaman `ensureBootstrap()`.
- `Dashboard.vue`: lee el bootstrap de la cache y muestra un resumen legible (cada catálogo con su
  conteo, items expandibles) + botón **Refrescar** (fuerza re-fetch). Fallback: si la cache está vacía
  (ej. sesión previa a esta feature), lo trae.
- **Fuera de alcance:** usar los catálogos para poblar selectores/mapear ids en otras pantallas (no hay
  otras pantallas todavía); invalidación por `version` (hoy el `version` solo se muestra).

---

## 2. Por qué "después de loguear" + cache (no solo on-mount del Dashboard)

El bootstrap se trae **una vez al obtener sesión** (login o registro, porque ambos dejan logueado) y se
cachea en `localStorage`. El Dashboard **lee de la cache**, no dispara la llamada como parte de su render.

Razón del fallback: al recargar la página (F5) el usuario sigue logueado (el token vive en `localStorage`)
pero el handler de login **no vuelve a correr**. Si la cache persiste en `localStorage`, sobrevive al
reload. El fallback `ensureBootstrap()` en el Dashboard cubre el caso de una cache ausente (sesión vieja).

`ensureBootstrap()` es **cache-first**: si ya hay bootstrap cacheado, no vuelve a llamar; si no, llama y
cachea. Así login/register/Dashboard pueden invocarlo sin duplicar requests.

---

## 3. Contrato con el backend

- `GET /bootstrap` con `Authorization: Bearer <token>` (el `request()` del cliente ya adjunta el token).
- Respuesta `{ version, catalogs: { currencies, obligation_types, income_types, priority_levels,
  institutions, review_finding_codes, credit_card_networks, credit_card_item_types } }`.
- Errores: `401 unauthenticated` si el token falta/expira → lo maneja el flujo de error ya existente
  (el `request()` lanza `Error` con `.code`). En la práctica no debería pasar justo después de loguear.

---

## 4. Estado en `localStorage`

- Clave `bootstrap`: el objeto completo `{ version, catalogs }` serializado.
- Se escribe en `ensureBootstrap()` / refresco; se borra en `clearSession()` (logout limpia token, user y bootstrap).

---

## 5. UI del Dashboard (mínima)

- Sección "Bootstrap  v{version}" con botón **Refrescar**.
- Por cada catálogo: una fila `nombre (conteo)` clickeable que expande/colapsa la lista de items.
- Render de items: genérico (no hay un schema fijo por catálogo en la web) — se muestra una línea por
  item con sus campos legibles (ej. `id · name`, y si no, el JSON del item). Sin diseño elaborado.
- Si no hay bootstrap (fallback falló o error), muestra el `message` del error como en las otras páginas.

---

## 6. Verificación

No hay test runner en la web (igual que web-auth): se verifica **`npm run build`** (compila sin errores)
y **a mano en el navegador** con el backend corriendo:
- registrarse/loguearse → el Dashboard muestra los 8 catálogos con conteos correctos (currencies de UY, etc.).
- recargar (F5) → el Dashboard sigue mostrando el bootstrap desde la cache (sin re-login).
- **Refrescar** → vuelve a traer del backend.
- cerrar sesión → se borra la cache (`localStorage` sin clave `bootstrap`).

---

## 7. Decisiones, con su porqué

- **Traer al loguear + cachear:** replica el flujo de la app real (diccionario cacheado, una sola llamada).
  El Dashboard consume cache, no la genera.
- **`ensureBootstrap()` cache-first + fallback en Dashboard:** robusto ante el reload (F5) y ante sesiones
  previas a la feature, sin requests duplicados.
- **Render genérico de catálogos:** es un banco de pruebas; no vale la pena un componente por catálogo.
  Lo importante es ver que el endpoint responde y qué trae.
- **Cache en `localStorage` (no en memoria):** sobrevive al reload, que es justo el caso a cubrir.
