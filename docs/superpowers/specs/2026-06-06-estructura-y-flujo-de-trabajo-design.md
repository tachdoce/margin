# Margin — Estructura del proyecto y flujo de trabajo con IA

> **Qué es este documento.** El *cómo* del proyecto: cómo se organizan los repos,
> cómo se estructura cada parte, y con qué método trabajamos usando IA.
> **No** documenta el producto — el *qué* vive en Notion:
> https://app.notion.com/p/Margin-372e504f64bb8033a2a0d65072414bf6

- **Fecha:** 2026-06-06
- **Estado:** aprobado para implementar
- **Equipo:** 2 personas — backend + web de pruebas (yo), app móvil (mi amigo)

---

## 1. Propósito y alcance

El producto (Margin: app de salud financiera para Uruguay, multi-moneda a futuro) ya
está bien definido en Notion. Lo que faltaba decidir es la **estructura del proyecto**
y el **flujo de trabajo con IA**. Este documento fija ambas cosas.

**Dentro de alcance:**
- Organización de repositorios.
- Estructura interna del backend y de la web de pruebas.
- El ciclo de trabajo con IA y el andamiaje que lo sostiene (`CLAUDE.md`, specs, planes, skills).

**Fuera de alcance:**
- La **app móvil** — vive en un repo aparte, propiedad de mi amigo, con su toolchain.
- El **diseño detallado de las features del producto** — eso es Notion, y cada feature
  tendrá su propio spec cuando se construya.

---

## 2. Estructura de repositorios (Enfoque A)

Un único repo de git (`margin`) con dos partes acopladas que cambian juntas, más la
app móvil viviendo aparte.

```
margin/                  ← un repo git (mío)
├── backend/             ← FastAPI + SQLAlchemy + Alembic + Postgres
├── web/                 ← Vue 3 + Vite (banco de pruebas de endpoints)
├── docs/
│   ├── specs/           ← specs de diseño (este archivo y los próximos)
│   └── plans/           ← planes de implementación
├── CLAUDE.md            ← contexto raíz para la IA
└── README.md

(aparte, otro repo)
mobile/                  ← app móvil (de mi amigo), consume el contrato OpenAPI
```

**La regla de la frontera:** nadie cruza repos. El **contrato es OpenAPI**, no el código.
FastAPI publica el esquema solo (`/openapi.json` y `/docs`); la web y, más adelante, el
mobile lo consumen sin leer el código del backend.

**Por qué Enfoque A:**
- Backend y web son ambos míos y cambian juntos (la web prueba el API) → conviene que
  vivan y se versionen en un mismo repo: un cambio de endpoint + su prueba es **un commit**
  que cuenta la historia completa.
- El mobile tiene otro dueño, otro toolchain y otra cadencia → meterlo en el monorepo
  agregaría fricción y ruido sin beneficio. Afuera, conectado por el contrato, queda limpio.

---

## 3. Stack (ya decidido)

**Backend (mío):**
- **FastAPI** — framework web; endpoints, validación, OpenAPI automático.
- **PostgreSQL 16** — base de datos (local: `margin` y `margin_test`, vía Homebrew).
- **SQLAlchemy** — ORM (modelos en `app/models/`).
- **Alembic** — migraciones de esquema.
- **Pydantic** + **pydantic-settings** — schemas de request/response (`app/schemas/`), config desde `.env`.
- **Uvicorn** — servidor ASGI.
- **python-jose** + **passlib/bcrypt** — JWT y hash de contraseñas.
- **psycopg2** — driver de Postgres.

**Web de pruebas (mía):**
- **Vue 3** con `<script setup>` (Composition API).
- **Vite** — bundler/dev server (`npm run dev`).
- **Vue Router** — navegación entre páginas (`/incomes`, `/plans`, …).

> La web tiene **poco diseño a propósito**: es banco de pruebas del API, no un producto.
> Botones que disparan endpoints y muestran el JSON. La prioridad es la funcionalidad, no la estética.

---

## 4. Estructura interna del backend

```
backend/
├── app/
│   ├── models/          ← SQLAlchemy (tablas)
│   ├── schemas/         ← Pydantic (request/response)
│   ├── engines/         ← familias de motores: PlanEngine, CashFlowEngine, ReviewEngine
│   ├── routers/         ← endpoints por subdominio
│   ├── core/            ← config, seguridad/JWT, sesión de DB
│   └── main.py          ← arranque de la app
├── alembic/             ← migraciones
├── tests/               ← pytest (usa la base margin_test)
└── CLAUDE.md            ← convenciones del backend
```

**Convenciones que no se negocian** (resumen; detalle en Notion → Convenciones generales):
- **Plata:** `numeric`, nunca `float`. Montos `numeric(12,2)`, tasas `numeric(5,2)`, cotizaciones `numeric(14,6)`.
- **Nombres:** tablas/columnas en inglés `snake_case`. Textos visibles al usuario en español.
- **Enums:** valores en español, patrón uniforme (excepción: `auth_provider` en inglés).
- **No se persiste lo derivable** (saldos, costos, "saldado"), salvo excepción de performance documentada junto al campo.
- **Borrado:** hard-delete por defecto; `deleted_at` solo donde se documente con su porqué.
- **Decisiones:** se documentan con su porqué. Lo descartado no se preserva; lo diferido va a `TODO / Pendientes`.

---

## 5. Estructura interna de la web

```
web/
├── src/
│   ├── pages/           ← una página por subdominio (/incomes, /plans, ...)
│   ├── router/          ← Vue Router
│   ├── api/             ← cliente HTTP que apunta al backend
│   └── main.js
├── index.html
└── CLAUDE.md            ← convenciones de la web ("poco diseño a propósito")
```

Misión única: disparar endpoints y mostrar el resultado. Apunta al backend por HTTP
(la URL base vive en config/env, no hardcodeada).

---

## 6. Flujo de trabajo con IA

El ciclo que seguimos en **cada pieza de trabajo**:

1. **Brainstorm → Spec.** Conversar la idea hasta tener un diseño escrito en `docs/specs/`.
2. **Spec → Plan.** El spec se vuelve un plan de implementación con pasos chicos y verificables, en `docs/plans/`.
3. **Plan → TDD.** Por cada paso: primero el test, después el código. El test es el contrato y la red de seguridad.
4. **Commits chicos / rebanadas verticales.** Cada paso que pasa sus tests es un commit que cuenta una historia.
5. **Code review antes de mergear.** La IA revisa el diff; yo evalúo cada sugerencia con criterio (no acepto ciego).
6. **Verificación antes de cantar victoria.** "Funciona" se demuestra corriendo el comando y mirando la salida.

> El proceso se siente más lento en el primer paso y evita el agujero clásico: código
> plausible que se rompe y nadie entiende por qué. En un producto financiero, esa
> disciplina no es opcional.

---

## 7. Andamiaje para la IA

- **`CLAUDE.md`** — contexto que la IA lee al arrancar cada sesión. Alta señal, poco ruido.
  - Raíz: qué es el proyecto, los dos pedazos, punteros a Notion, el flujo de trabajo.
  - `backend/`: convenciones de FastAPI/SQLAlchemy/Alembic, reglas de plata/enums, comandos (correr, testear, migrar).
  - `web/`: convenciones de Vue, "poco diseño a propósito", cómo apunta al backend.
  - Regla: punteros, no copias. Nada que la IA ya pueda leer del código. Nada que cambie todo el tiempo.
- **`docs/specs/`** — specs de diseño por feature.
- **`docs/plans/`** — planes de implementación por feature.

---

## 8. Skills que adoptamos

**Núcleo (desde el día 1):**
- `brainstorming` — idea → spec.
- `writing-plans` — spec → plan.
- `test-driven-development` — test antes que código.
- `verification-before-completion` — no cantar victoria sin correr el comando.

**Cuando hagan falta (no antes):**
- `systematic-debugging`, `requesting-code-review` / `receiving-code-review`,
  `executing-plans`, `using-git-worktrees`.

Más adelante podemos escribir **skills propias de Margin** para procedimientos repetitivos
(ej. "agregar un endpoint nuevo", "crear una migración", "agregar un motor a una familia").

---

## 9. Primera rebanada vertical

Para tener un objetivo concreto apenas terminado el setup, la primera iteración será un
**endpoint real de punta a punta**: schema Pydantic → modelo SQLAlchemy → migración Alembic
→ endpoint FastAPI → test (pytest) → botón en la web que lo dispara y muestra el JSON.

El subdominio concreto se elige al pasar a `writing-plans` (candidato natural: `auth` o
`incomes`, por ser puerta de entrada del resto). Esta primera vuelta sirve además como
recorrido guiado del flujo: cada skill se nombra a medida que aparece.

---

## 10. Decisiones, con su porqué

- **Enfoque A (monorepo backend+web, mobile aparte):** respeta los límites de propiedad,
  mantiene juntas las piezas acopladas y deja el mobile prolijo vía contrato OpenAPI.
- **Web de pruebas propia:** desbloquea el desarrollo del backend sin depender de que la app
  esté lista (mi amigo tiene poco tiempo al inicio); además queda como banco de pruebas permanente.
- **Flujo spec→plan→TDD→review→verificación:** evita el código plausible-pero-roto; crítico
  en un producto financiero donde el usuario confía sus deudas.
- **`CLAUDE.md` + skills:** convierten el conocimiento (mío y de Notion) en contexto y método
  que la IA usa de forma consistente, sesión tras sesión.
