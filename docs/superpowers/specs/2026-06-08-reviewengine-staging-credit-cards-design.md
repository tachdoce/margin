# ReviewEngine.staging_credit_cards (reviewer) — Diseño

> Sub-proyecto del subdominio **Tarjetas de crédito**. El reviewer que revisa los datos generales del estado
> de cuenta cargado en cada `staging_credit_cards` (la fila madre), produce los `review_findings` y aplica la
> transición del ciclo de revisión (incluido `is_ready`, el gate que habilita **promover**). **Solo el
> reviewer**, sin endpoints ni promote. El *qué* está en Notion → Backend → Engines → ReviewEngine →
> `staging_credit_cards` (+ el ciclo transversal en BD → Tarjetas de crédito → Ciclo de revisión).

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tablas `staging_credit_cards` y `credit_cards` (ya en el repo), `review_finding_codes`
  (catálogo ya seedeado: `closing_after_due`, `due_date_in_future`, `due_date_too_old`, `rates_not_updated`,
  `new_card` existen).
- **Cierre:** rama `feat/review-staging-credit-cards`, **squash-merge** a `main`.

---

## 1. Alcance

Crear `app/services/review/staging_credit_cards.py` con
`review_staging_credit_card(db, staging_credit_card_id, *, today=None)`, más tests. La función corre los
chequeos sobre la fila madre y aplica la transición del ciclo. No hace commit (lo controla el caller).

**Fuera de alcance:** los endpoints (`POST/PUT staging-credit-card-statements` que cargan/editan y resetean el
ciclo), la promoción, el reviewer de `credit_cards`, el `CashFlowEngine.credit_cards`. Sub-proyectos
posteriores.

Espeja el patrón de `app/services/review/obligations.py` (`review_obligation`): bloqueo de la fila con
`with_for_update`, cómputo de findings, transición del ciclo, `db.flush()` sin commit. **Sin** el
short-circuit de `is_closed` (el staging no se cierra).

---

## 2. Reglas que chequea

Sobre los datos crudos de la fila madre. Cada regla trae su **guarda de NULL**: la madre entra incompleta, así
que una regla solo se evalúa si los campos que necesita tienen valor (salvo `rates_not_updated`, que dispara
*por* el NULL).

| code | regla | guarda |
|---|---|---|
| `closing_after_due` | `closing_date > due_date` | `closing_date` **y** `due_date` con valor |
| `due_date_in_future` | `due_date > today + 60 días` | `due_date` con valor |
| `due_date_too_old` | `due_date < (today − 12 meses)` | `due_date` con valor |
| `rates_not_updated` | alguna de las 4 tasas (`financing_rate_local`, `overdue_rate_local`, `financing_rate_usd`, `overdue_rate_usd`) **o** `rates_add_vat` es NULL | — |
| `new_card` | no existe **ninguna** `credit_cards` del usuario para ese `(institution_id, card_network_id)` | `institution_id` **y** `card_network_id` con valor |

**`new_card` — decisión del usuario:** la existencia se chequea **sin filtrar por `deleted_at`**: si hay
alguna `credit_cards` con ese `(user_id, institution_id, card_network_id)`, aunque esté soft-deleted, **no**
se emite el finding. Es coherente con que el promote reactiva una tarjeta soft-deleted (no crea una nueva); el
finding solo avisa "se dará de alta una tarjeta nueva" cuando no existe ninguna fila para esa combinación.

**`due_date_too_old` — "12 meses" calendario-correcto:** sin `dateutil` disponible, se calcula el corte
restando 12 meses a `today` con clamp de día (un helper `_months_ago(today, 12)`): p.ej. desde 2026-06-08 el
corte es 2026-06-08 − 12m = 2025-06-08; `due_date < corte` dispara. El clamp cubre meses sin ese día (29/2 →
28/2). No se aproxima con 365 días.

---

## 3. Transición del ciclo

Tras computar la lista de findings (codes, sin duplicados, ordenados con `sorted(set(...))` para determinismo):

- `staging.reviewed_at = now` (timestamp de la corrida).
- `staging.review_findings = json.dumps(findings)` (array JSON de strings; `'[]'` si no hay).
- `staging.is_ready = (findings está vacío)`.
- Si hay findings → `staging.user_acknowledged_at = None` (invalida una aceptación previa). Si no hay
  findings → **no** se toca `user_acknowledged_at`.

El reviewer corre **incondicional** cuando se lo invoca: no chequea `reviewed_at IS NULL` ni decide cuándo
correr. La cola (`reviewed_at IS NULL`) y el reset del ciclo ante cambios de datos de negocio son del
**endpoint** (sub-proyecto posterior), que resetea y luego invoca al reviewer.

`db.flush()` al final (sin commit).

---

## 4. Decisiones, con su porqué

- **Reviewer solo, sin endpoints:** mismo enfoque que `ReviewEngine.obligations`; el wiring (reset del ciclo +
  reviewer → promote/CashFlowEngine) vive en el slice de endpoints.
- **`new_card` incluye soft-deleted (decisión del usuario):** evita un falso "tarjeta nueva" cuando el promote
  en realidad reactivará una soft-deleted. La query no filtra por `deleted_at`.
- **`new_card` solo concluyente con emisor y red resueltos:** con alguno en NULL no hay contra qué comparar;
  no se emite (lo dice Notion).
- **`today` inyectable (`today=None` → `date.today()`):** mismo patrón que los motores `CashFlowEngine`, para
  tests deterministas de las reglas de fecha.
- **`due_date_too_old` calendario-correcto vía `_months_ago`:** "12 meses" es calendario, no 365 días; sin
  `dateutil`, se resuelve con `calendar.monthrange` + clamp de día.
- **Findings ordenados y sin duplicados:** determinismo en tests y en el JSON persistido.
- **Incondicional al invocarse:** la decisión de cuándo correr (cola, reset anti-loop) es del endpoint; el
  reviewer es una función pura de "revisá esta fila y dejá el ciclo".
- **`with_for_update` sobre la madre:** igual que el reviewer de obligaciones, para serializar con escrituras
  concurrentes del ciclo.

---

## 5. Tests (`tests/test_review_staging_credit_cards.py`)

Sembrando UY + Peso + institución + red (reusar `seed_cc_refs` de conftest) + una `staging_credit_cards`
(helper que crea la madre mínima y permite override de campos). `today` fijo (p.ej. `date(2026, 6, 8)`) para
las reglas de fecha. Releer la madre tras `review_staging_credit_card` para ver el ciclo.

- **Madre vacía** (todo NULL salvo ciclo + user): dispara **solo** `rates_not_updated` (las 4 tasas y
  `rates_add_vat` en NULL); las demás reglas no aplican por sus guardas (sin fechas, sin emisor/red).
  `is_ready is False`.
- **Sin findings:** fechas sanas (`closing_date <= due_date`, `due_date` dentro de rango), las 4 tasas y
  `rates_add_vat` con valor, y **existe** una `credit_cards` del usuario para ese emisor+red →
  `review_findings == '[]'`, `is_ready is True`, `reviewed_at` no NULL.
- **`closing_after_due`:** `closing_date=2026-05-20`, `due_date=2026-05-10` → el code aparece.
- **`closing_after_due` requiere ambas:** `closing_date` con valor y `due_date=None` → no dispara (y tampoco
  las reglas de `due_date`).
- **`due_date_in_future`:** `due_date = today + 61 días` → dispara; `today + 60` exacto → no dispara.
- **`due_date_too_old`:** `due_date = _months_ago(today,12) − 1 día` → dispara; justo en el corte → no.
- **`rates_not_updated` por una sola tasa:** 3 tasas con valor y `financing_rate_usd=None` → dispara; con las
  4 tasas y `rates_add_vat` con valor → no.
- **`new_card` cuando no hay tarjeta:** madre con emisor+red resueltos y **sin** `credit_cards` del usuario →
  dispara.
- **`new_card` NO dispara con soft-deleted:** existe una `credit_cards` de ese emisor+red con `deleted_at`
  seteado → no se emite `new_card`.
- **`new_card` requiere emisor y red:** `card_network_id=None` → no se emite (aunque no haya tarjeta).
- **Varias reglas juntas:** ordenadas, sin duplicados; `is_ready is False`.
- **Reset de acknowledge:** con `user_acknowledged_at` seteado y un resultado con findings → queda `None`; con
  resultado sin findings → se mantiene.
- **`review_findings` es JSON válido:** `json.loads` devuelve una lista de strings.

> Los tests arman el schema con `create_all` (conftest). El helper de la madre y el de crear una `credit_cards`
> del usuario (vigente / soft-deleted) viven en el test file; reusar `seed_cc_refs` y `_card_kwargs`
> (`tests/test_credit_cards_model.py`) donde convenga.

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/review-staging-credit-cards`), TDD:
1. `tests/test_review_staging_credit_cards.py` (rojo) → `app/services/review/staging_credit_cards.py`
   (`_months_ago`, `_findings`, `review_staging_credit_card`) (verde) → commit.
2. Suite completa verde → cierre.
