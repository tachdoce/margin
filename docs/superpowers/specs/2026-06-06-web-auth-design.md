# Web de pruebas — Auth (signin/signup → dashboard) — Diseño

> **Qué es este documento.** El diseño de la primera rebanada de la web de pruebas de Margin:
> registro, login y un dashboard mínimo, consumiendo el backend real. La web vive en el
> monorepo (`margin/web/`) — ver `docs/superpowers/specs/2026-06-06-estructura-y-flujo-de-trabajo-design.md`.

- **Fecha:** 2026-06-06
- **Estado:** aprobado para implementar
- **Depende de:** backend con `POST /auth/register` y `POST /auth/login` (ya en `main`).

---

## 1. Contexto y decisiones de encuadre

- Existe un PoC previo en `/Users/tachone/proyectos/margin-web/` (primer experimento con IA). **No se reutiliza el código** — se construye de cero. El PoC queda como referencia (su `design-system.md` es útil para la app móvil del compañero). No se borra.
- La web **vive en el monorepo** `margin/web/` (Enfoque A): un solo git con backend + web.
- La web **usa el design-system** del PoC (Inter, índigo, mobile-first 390px). No es "fea": tiene estilo, pero su función sigue siendo **probar los endpoints**.

---

## 2. Proyecto y stack

- Vue 3 (`<script setup>`) + Vite + Vue Router, nuevo en `margin/web/`.
- Dependencias mínimas: `vue`, `vue-router`, `vite`, `@vitejs/plugin-vue`. Nada más (sin pdfjs).
- Dev server de Vite (por defecto `http://localhost:5173`). El backend corre en `http://localhost:8000`.

---

## 3. Estilo (design-system)

- `src/style.css` contiene: el `@import` de Inter, el bloque `:root` de **tokens** (colores, `--radius`, `--max-width: 390px`), el reset, y el CSS de los componentes que se usan en esta rebanada:
  - layout `.screen` / `.content` (columna centrada a 390px),
  - botón `.primary` (índigo) y `.ghost`,
  - inputs `.field` / `label` / `input`,
  - textos de estado `.error` / `.muted`.
- Los valores salen tal cual del `design-system.md` (fuente de verdad del look). Mobile-first.

---

## 4. Cliente del API (`src/api.js`)

Wrapper `fetch` fino. Matchea el **contrato real** del backend:

- `register(email, password, displayName?)` → `POST /auth/register` con body `{ email, password, display_name }` (omitir `display_name` si vacío).
- `login(email, password)` → `POST /auth/login` con body `{ email, password }`.
- Ambos devuelven `{ user: { id, country_code, display_name }, token }`.
- El `token` se guarda en `localStorage` (clave `token`); el `user` también (clave `user`, JSON).
- En requests autenticados futuros se manda `Authorization: Bearer <token>` (ya preparado, aunque hoy ningún endpoint lo exige).
- **Errores:** si `!res.ok`, parsea el envelope `{ code, message, field? }` (o el wrapper `{ code:"validation_failed", message, errors:[] }`) y lanza un `Error` con `.code`, `.message`, `.field` para que la vista los muestre.

---

## 5. Vistas

- **`Register.vue`** — form con `email`, `password`, `display_name` (opcional). Al enviar: `api.register(...)`, guarda token+user, navega a `/dashboard`. Muestra el `message` del backend si falla (ej. `email_already_registered`, `password_too_short`, `email_invalid`), resaltando el `field` si viene.
- **`Login.vue`** — form con `email`, `password`. Al enviar: `api.login(...)`, guarda token+user, navega a `/dashboard`. Muestra `"Credenciales inválidas."` ante `credentials_invalid`. Link a `/register`.
- **`Dashboard.vue`** — lee el `user` de `localStorage` y muestra `id`, `country_code`, `display_name`. Botón **Cerrar sesión** (borra token+user de `localStorage` y navega a `/login`).

---

## 6. Router y guard

- Rutas: `/login`, `/register`, `/dashboard`.
- `/` redirige a `/dashboard` si hay token, si no a `/login`.
- **Guard global:** `/dashboard` requiere token en `localStorage`; sin token → redirige a `/login`. Las rutas `/login` y `/register` son públicas (si ya hay token, opcionalmente redirigen a `/dashboard`).

---

## 7. Backend: habilitar CORS (cambio necesario)

El navegador bloquea las llamadas de `http://localhost:5173` → `http://localhost:8000` si el backend no autoriza ese origen. Se agrega el `CORSMiddleware` de FastAPI en `app/main.py`, permitiendo el origen del dev server de la web. Los orígenes permitidos salen de config (`Settings`), con un default para desarrollo (`http://localhost:5173`). Métodos y headers necesarios habilitados.

---

## 8. Verificación

Banco de pruebas → verificación **manual** del flujo en el navegador:
1. Levantar backend (`uvicorn`) y web (`npm run dev`).
2. Registrarse → llega al dashboard con sus datos.
3. Logout → vuelve al login.
4. Login con esas credenciales → dashboard.
5. Errores: registrar email repetido muestra *"Ese email ya está registrado."*; login con password mala muestra *"Credenciales inválidas."*.
6. Entrar a `/dashboard` sin token redirige a `/login`.

Tests automatizados de frontend (vitest) se difieren (YAGNI por ahora).

---

## 9. Alcance

**Dentro:** proyecto Vue en `margin/web/`, estilo del design-system, `api.js` (register/login), vistas Register/Login/Dashboard, router + guard, CORS en el backend.

**Fuera (futuro):** vistas de `countries`/`incomes`/`plans`/`pdf`, endpoint protegido `GET /me`, tests de frontend, deploy. La app móvil (del compañero) sigue siendo otro repo.

---

## 10. Decisiones, con su porqué

- **De cero, sin reusar el PoC:** el scaffold previo apunta a endpoints inventados (`/incomes`, `/plans`…) y manda `name` en vez de `display_name`; arrastra cruft. Empezar limpio contra el contrato real es más sano que depurar código especulativo.
- **En el monorepo (`margin/web/`):** mantiene Enfoque A (un git para backend + web, acoplados por el contrato OpenAPI).
- **Con estilo (design-system) pero función de prueba:** el estilo ya está pensado y no cuesta aplicarlo; la web sigue siendo el banco de pruebas del API.
- **Token en `localStorage`:** simple para un cliente de prueba en dev (no es la app de producción).
- **CORS desde config:** evita hardcodear orígenes y deja listo sumar más (deploy) sin tocar código.
