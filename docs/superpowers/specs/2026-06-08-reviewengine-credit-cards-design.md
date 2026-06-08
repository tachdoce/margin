# ReviewEngine.credit_cards (reviewer) — Diseño

> Sub-proyecto del subdominio **Tarjetas de crédito**. El reviewer que revisa la tarjeta definitiva
> (`credit_cards`, ya promovida), produce los `review_findings` y aplica la transición del ciclo de revisión
> (incluido `is_ready`, el gate que habilita la materialización del `CashFlowEngine.credit_cards`). **Solo el
> reviewer**, sin endpoints ni promote. El *qué* está en Notion → Backend → Engines → ReviewEngine →
> `credit_cards` (+ el ciclo transversal en BD → Tarjetas de crédito → Ciclo de revisión).

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tablas `credit_cards` y `credit_card_statements` (ya en el repo), `review_finding_codes`
  (catálogo ya seedeado: `closing_day_inferred`, `closing_day_changed` existen).
- **Cierre:** rama `feat/review-credit-cards`, **squash-merge** a `main`.

---

## 1. Alcance

Crear `app/services/review/credit_cards.py` con `review_credit_card(db, credit_card_id)`, más tests. La función
corre los chequeos sobre la tarjeta y aplica la transición del ciclo. No hace commit (lo controla el caller).

**Fuera de alcance:** los endpoints (promote/PATCH/acknowledge que resetean el ciclo y orquestan reviewer →
`CashFlowEngine.credit_cards`), el motor, el reviewer de `staging_credit_cards` (ya hecho).

Espeja `app/services/review/staging_credit_cards.py` y `obligations.py`: bloqueo `with_for_update`, cómputo de
findings, transición del ciclo, `db.flush()` sin commit. **No** recibe `today` (sus reglas no comparan contra
hoy).

---

## 2. Reglas que chequea

Las dos reglas son **mutuamente excluyentes** según `created_at == updated_at`:

| code | condición | rama |
|---|---|---|
| `closing_day_inferred` | `created_at == updated_at` (tarjeta recién creada) | nueva |
| `closing_day_changed` | `created_at != updated_at` (existente) **y** `abs(día(closing_date del último resumen) − closing_day) > 4` | existente |

`CLOSING_DAY_CHANGE_THRESHOLD = 4` (valor absoluto, en días del mes).

**De qué resumen sale `closing_day_changed`:** el reviewer recibe solo el `credit_card_id`, así que consulta el
**último resumen** de la tarjeta (mayor `issue_year`, luego mayor `issue_month`) y toma el día de su
`closing_date`. Si la tarjeta no tiene ningún `credit_card_statements`, la regla no se evalúa (no se emite).

---

## 3. Cómo distingue "recién creada" de "editada"

Compara `card.created_at == card.updated_at` (criterio de Notion). Es confiable porque en Postgres `now()` /
`CURRENT_TIMESTAMP` es **fijo por transacción**:

- **Tarjeta nueva:** el INSERT (promote) y la corrida del reviewer ocurren en la **misma** transacción → ambos
  timestamps toman el mismo `now()` → iguales → `closing_day_inferred`.
- **Tarjeta existente:** el UPDATE de datos de negocio (promote de un resumen posterior, o un PATCH del
  usuario) ocurrió en **otra** transacción → `updated_at` quedó distinto de `created_at` → rama
  `closing_day_changed`.
- **La escritura del ciclo del propio reviewer no rompe el criterio:** (a) el reviewer **lee**
  `created_at`/`updated_at` antes de escribir las columnas del ciclo; (b) aunque el UPDATE del ciclo dispare el
  `onupdate=now()` de `updated_at`, dentro de la misma transacción ese `now()` es el mismo valor que ya tenía
  (transaction-fixed), así que no cambia el resultado. Esto materializa la "Regla de updated_at" (el ciclo no
  altera `updated_at`) sin necesitar manejo especial.

> El requisito de que el promote setee `created_at == updated_at` al insertar y no toque `updated_at` antes del
> reviewer es del sub-proyecto del endpoint; este reviewer solo implementa la comparación.

---

## 4. Transición del ciclo

Tras computar la lista de findings (codes, sin duplicados, ordenados con `sorted(set(...))`):

- `card.reviewed_at = now`.
- `card.review_findings = json.dumps(findings)` (`'[]'` si no hay).
- `card.is_ready = (findings está vacío)`.
- Si hay findings → `card.user_acknowledged_at = None`. Si no hay → no se toca.

Incondicional al invocarse. `db.flush()` al final (sin commit). La cola (`reviewed_at IS NULL`) y el reset del
ciclo ante cambios de negocio son del endpoint.

---

## 5. Decisiones, con su porqué

- **Reviewer solo, sin endpoints:** mismo enfoque que los otros reviewers; el wiring vive en el slice de
  endpoints.
- **Nueva vs existente por `created_at == updated_at`:** criterio de Notion, robusto por el `now()`
  transaction-fixed de Postgres (§3). Evita una columna o flag extra.
- **`closing_day_changed` contra el último resumen (no un parámetro):** firma uniforme (solo `credit_card_id`),
  coherente con las 3 vías que lo invocan (promote/PATCH/acknowledge) — siempre "closing_day vs el resumen más
  reciente". Sin resumen → no se evalúa.
- **Reglas mutuamente excluyentes:** una tarjeta recién creada solo puede emitir `closing_day_inferred` (su
  `closing_day` se infirió de su único/primer resumen, así que comparar contra él no aporta); una existente
  solo `closing_day_changed`. La rama por `created_at == updated_at` lo garantiza.
- **Umbral 4 días absoluto:** valor de Notion; constante nombrada.
- **Sin `today`:** ninguna regla compara contra la fecha actual (a diferencia del reviewer de staging).

---

## 6. Tests (`tests/test_review_credit_cards.py`)

Reusar `seed_cc_refs` (conftest) y `_card_kwargs` (`tests/test_credit_cards_model.py`). Helpers locales para
crear la tarjeta (con override de `closing_day` y de `created_at`/`updated_at`) y un `credit_card_statements`
(con override del día del `closing_date` y del período). Releer la tarjeta tras `review_credit_card`.

> Para una tarjeta **nueva** se inserta sin pasar timestamps (los server-default dan `created_at == updated_at`
> en la transacción del test). Para una **existente** se pasan `created_at` y `updated_at` explícitos y
> distintos (dentro de una sola transacción no se pueden obtener dos `now()` diferentes).

- **Tarjeta nueva → `closing_day_inferred`:** insertar sin timestamps explícitos → el code aparece,
  `is_ready is False`, `reviewed_at` no NULL.
- **Nueva NO emite `closing_day_changed`:** tarjeta nueva con `closing_day=13` y un resumen con `closing_date`
  día 25 (dif 12) → findings == `["closing_day_inferred"]` (la rama existente no corre).
- **Existente sin findings:** `created_at=T1`, `updated_at=T2` (T2>T1), `closing_day=13`, último resumen día 13
  → `review_findings == '[]'`, `is_ready is True`.
- **Existente → `closing_day_changed`:** mismas condiciones pero último resumen día 20 (dif 7 > 4) → el code
  aparece, `is_ready is False`.
- **Boundary del umbral:** dif exactamente 4 (día 17 vs 13) → no dispara; dif 5 (día 18) → dispara.
- **Existente sin resumen:** `created_at != updated_at` y la tarjeta sin `credit_card_statements` → no emite
  `closing_day_changed` (findings vacío, `is_ready True`).
- **Usa el último resumen por período:** existente con dos resúmenes — uno 2026/04 día 13 (dif 0) y otro
  2026/05 día 25 (dif 12) → dispara `closing_day_changed` (toma el de 2026/05).
- **Reset de acknowledge:** existente con `user_acknowledged_at` seteado y un resultado con findings → queda
  `None`; con resultado sin findings → se mantiene.
- **`review_findings` es JSON válido:** `json.loads` devuelve una lista de strings.
- **Fila inexistente:** `review_credit_card(db, uuid4())` → no-op, sin error.

---

## 7. Plan de implementación (orientativo)

Un slice (`feat/review-credit-cards`), TDD:
1. `tests/test_review_credit_cards.py` (rojo) → `app/services/review/credit_cards.py`
   (`_latest_statement_closing_day`, `_findings`, `review_credit_card`) (verde) → commit.
2. Suite completa verde → cierre.
