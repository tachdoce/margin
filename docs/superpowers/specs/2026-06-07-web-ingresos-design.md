# Web: menú drawer + vista Ingresos (CRUD de prueba) — Diseño + plan

> Feature de la web de pruebas (banco de pruebas, poco diseño). Por convención del proyecto, en la web
> se comprime spec+plan en un solo doc liviano (backend lleva los 3 gates; web = aprobar diseño + avisar).
> Diseño aprobado vía companion visual: menú **drawer lateral** + vista **Ingresos** con CRUD completo.

- **Fecha:** 2026-06-07
- **Estado:** aprobado para implementar
- **Depende de:** endpoints de incomes (POST/GET/PATCH/DELETE/reactivate, en `main`) y el bootstrap cacheado
  (`getBootstrap()` con `catalogs.income_types` y `catalogs.currencies`).
- **Cierre:** rama `feat/web-ingresos`, **squash-merge** a `main`.

---

## 1. Alcance

- **Menú hamburguesa (drawer lateral):** ☰ en una barra superior; abre un panel desde la izquierda con
  overlay oscuro. Items: **Dashboard** (1º) e **Ingresos** (2º), + "Cerrar sesión". Resalta la ruta activa.
  Aparece en las páginas autenticadas (Dashboard, Ingresos), no en Login/Register.
- **Vista Ingresos (`/incomes`):** CRUD de prueba de los 5 endpoints — listar, crear, editar, borrar, reactivar.

Sin test runner en la web → verificación por `npm run build` + a mano en el navegador (precedente web-auth/web-bootstrap).

---

## 2. Archivos

```
web/src/
├── api/index.js            # + métodos incomes (list/create/update/delete/reactivate)   (MODIFICAR)
├── components/AppNav.vue    # barra + drawer hamburguesa   (NUEVO)
├── pages/Incomes.vue        # vista CRUD de ingresos   (NUEVO)
├── pages/Dashboard.vue      # + <AppNav /> arriba   (MODIFICAR)
├── router/index.js          # + ruta /incomes (guardada)   (MODIFICAR)
└── style.css                # + estilos de nav/drawer y de la vista   (MODIFICAR)
```

---

## 3. API (`web/src/api/index.js`)

Agregar al objeto `api` (el `request()` ya adjunta el Bearer):
- `listIncomes()` → `GET /incomes` → `{ incomes: [...] }`.
- `createIncome(body)` → `POST /incomes`.
- `updateIncome(id, body)` → `PATCH /incomes/${id}`.
- `deleteIncome(id)` → `DELETE /incomes/${id}` (204 → `request` ya devuelve `null`).
- `reactivateIncome(id)` → `POST /incomes/${id}/reactivate`.

---

## 4. `AppNav.vue` (componente, drawer lateral)

- Barra superior fija: botón ☰ + título "Margin".
- Estado `open` (ref). ☰ abre; click en overlay o en un item cierra.
- Drawer izquierdo (overlay `rgba(17,24,39,.35)`): `<router-link>` a `/dashboard` y `/incomes` (item activo
  resaltado con la clase de Vue Router `router-link-active`), y abajo "Cerrar sesión" (`clearSession()` + ir a `/login`).
- Se incluye al tope de Dashboard e Incomes (2 páginas; sin refactor de router por YAGNI).

---

## 5. `Incomes.vue` (vista CRUD)

**Carga:** `onMounted` → `api.listIncomes()` a un ref `incomes`; `getBootstrap()` para poblar los selects
(si no hay cache, `ensureBootstrap()`). Mapea `income_type_id`/`currency_id` → nombre vía los catálogos.

**Form de alta/edición (un mismo form, modo `create` o `edit`):**
- `income_type_id` (select de `catalogs.income_types`), `currency_id` (select de `catalogs.currencies`,
  default = la `is_legal_tender`), `amount`, `description`.
- Toggle **Recurrente / Duración fija** (`is_monthly_recurring`):
  - recurrente → muestra `payment_day` (manda `first_income_date`/`total_months` = null).
  - duración fija → muestra `first_income_date` + `total_months` (manda `payment_day` = null).
- Checkbox `shift_weekends`.
- **Crear:** `api.createIncome(body)` con el set consistente según la forma. **Editar:** `api.updateIncome(id, body)`
  mandando los campos de la forma final (incluye los `null` para mantener consistencia del modelo binario).
- Errores del backend → mostrar `e.message` arriba del form (mismo patrón que Login/Register).
- Al éxito: limpiar/cerrar el form y recargar la lista.

**Lista:**
- Render de cada income: descripción, `amount` + moneda, nombre del tipo, resumen de forma
  ("Recurrente, día 5" / "Duración fija, 2026-07-10 ×N").
- Activos (`is_deleted=false`): botones **Editar** y **Borrar** (`deleteIncome` → recargar).
- Borrados (`is_deleted=true`): atenuados, badge "borrado", botón **Reactivar** (`reactivateIncome` → recargar).

> `amount` viaja como string (Pydantic serializa Decimal como string); el form lo manda como string y se
> muestra tal cual (sin parseos de moneda elaborados — es banco de pruebas).

---

## 6. Router (`web/src/router/index.js`)

Agregar `{ path: '/incomes', component: Incomes }` (no `public` → cae bajo el guard de auth existente).

---

## 7. Verificación

- `npm run build` compila sin errores.
- A mano (backend + `npm run dev`): abrir el drawer, navegar Dashboard ↔ Ingresos; crear un recurrente y
  uno de duración fija; ver la lista; editar uno; borrar (pasa a "borrado") y reactivar; provocar un error
  (monto 0) y ver el mensaje del backend.

---

## 8. Decisiones

- **`<AppNav />` por página** (no layout con rutas anidadas): solo 2 páginas autenticadas; YAGNI.
- **Selects desde el bootstrap cacheado:** reusa lo que ya trae la web; sin llamadas extra.
- **Un solo form create/edit:** DRY; el modo lo decide si hay un income seleccionado.
- **Mandar nulls explícitos al editar la forma:** respeta la validación binaria del backend (estado final).
