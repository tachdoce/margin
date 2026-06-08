# ReviewEngine.obligations (reviewer) — Diseño

> Sub-proyecto #5 del subdominio **Obligaciones**. El reviewer que revisa los datos cargados en cada
> `obligations`, produce los `review_findings` y aplica la transición del ciclo de revisión (incluido
> `is_ready`, el gate que leen los motores `expenses`/`debts`/`open_debts`). **Solo el reviewer**, sin
> endpoints. El *qué* está en Notion → Backend → Engines → ReviewEngine → `obligations` (+ el ciclo
> transversal en BD → Obligaciones).

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tabla `obligations`, `review_finding_codes` (catálogo ya seedeado: los codes
  `overdue_lower_than_financing` y `rate_above_threshold` existen).
- **Cierre:** rama `feat/review-obligations`, **squash-merge** a `main`.

---

## 1. Alcance

Crear `app/services/review/obligations.py` con `review_obligation(db, obligation_id)`, más tests. La función
corre los chequeos sobre la obligación y aplica la transición del ciclo. No hace commit (lo controla el
caller).

**Fuera de alcance:** los endpoints (que resetean el ciclo y orquestan reviewer → CashFlowEngine), el POST
acknowledge, los reviewers de otros subdominios.

---

## 2. Reglas que chequea

> **Decisión del usuario:** la regla `amount_above_threshold` (umbral de monto por moneda) **NO se
> implementa** — se descarta. El reviewer arranca con las **2 reglas de tasas**. Se sumarán más a medida que
> aparezcan casos reales.

Sobre las tasas **crudas** de la obligación (`financing_rate`, `overdue_rate`, tal como las cargó el
usuario — no las efectivas):

| code | regla |
|---|---|
| `overdue_lower_than_financing` | `overdue_rate < financing_rate` (las **dos** con valor) |
| `rate_above_threshold` | `financing_rate > 150` **o** `overdue_rate > 150` (cualquiera con valor) |

Una tasa NULL no dispara ninguna regla que la involucre (la regla solo aplica si la(s) tasa(s) que necesita
tienen valor).

---

## 3. Transición del ciclo

Tras computar la lista de findings (codes, sin duplicados, ordenados para determinismo):

- `obligation.reviewed_at = now` (timestamp de la corrida).
- `obligation.review_findings = json.dumps(findings_ordenados)` (array JSON de strings; `'[]'` si no hay).
- `obligation.is_ready = (findings está vacío)`.
- Si hay findings → `obligation.user_acknowledged_at = None` (invalida una aceptación previa). Si no hay
  findings → **no** se toca `user_acknowledged_at` (regla "Reset del reconocimiento" del ReviewEngine).

El reviewer corre **incondicional** cuando se lo invoca: no chequea `reviewed_at IS NULL` ni decide cuándo
correr. La cola (`reviewed_at IS NULL`) y el reset del ciclo ante cambios de datos de negocio son
responsabilidad del **endpoint** (slice #6), que resetea y luego invoca al reviewer.

`db.flush()` al final (sin commit).

---

## 4. Decisiones, con su porqué

- **Reviewer solo, sin endpoints:** mismo enfoque que los motores; el wiring (reset del ciclo + reviewer →
  CashFlowEngine en la misma transacción) vive en el slice de endpoints.
- **Sobre tasas crudas, no efectivas:** el reviewer revisa lo que cargó el usuario; la conversión a efectiva
  (IVA) es del motor `debts` al materializar.
- **`amount_above_threshold` descartada (decisión del usuario):** evita además la ambigüedad de identificar
  la moneda (UYU/USD) que el modelo `currencies` no expresa con código ISO.
- **Findings ordenados y sin duplicados:** determinismo en tests y en el JSON persistido; el formato (array
  de codes) lo fija `ReviewEngine → Formato de review_findings`.
- **Incondicional al invocarse:** la decisión de cuándo correr (cola, reset anti-loop) es del endpoint; el
  reviewer es una función pura de "revisá esta fila y dejá el ciclo".

---

## 5. Tests (`tests/test_review_obligations.py`)

Sembrando UY + currency + priority_levels + obligation_type de deuda + usuario + una `obligations` de deuda
(helper). Releer la obligación tras `review_obligation` para ver el ciclo.

- **Sin findings** (tasas sanas, ej. `financing_rate=50`, `overdue_rate=60`): `review_findings == '[]'`,
  `is_ready is True`, `reviewed_at` no NULL.
- **`overdue_lower_than_financing`** (`overdue_rate=30 < financing_rate=50`): el code aparece;
  `is_ready is False`.
- **`rate_above_threshold`** (`financing_rate=160`): el code aparece; `is_ready is False`.
- **Dos reglas juntas** (`financing_rate=200`, `overdue_rate=10`): ambos codes presentes, ordenados, sin
  duplicados; `is_ready is False`.
- **Tasas NULL:** `financing_rate=None`, `overdue_rate=None` → sin findings, `is_ready is True` (ninguna
  regla de tasa se evalúa).
- **`overdue_lower_than_financing` requiere ambas:** solo `financing_rate` con valor y `overdue_rate=None` →
  no dispara esa regla.
- **Reset de acknowledge:** con `user_acknowledged_at` seteado y un cambio que produce findings → queda
  `None`; con resultado sin findings → `user_acknowledged_at` se mantiene.
- **`review_findings` es JSON válido:** parsear con `json.loads` devuelve una lista de strings.

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/review-obligations`), TDD:
1. `tests/test_review_obligations.py` (rojo) → `app/services/review/obligations.py` (verde) → commit.
2. Suite completa verde → cierre.
