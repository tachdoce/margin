# GET / DELETE / acknowledge staging-credit-card-statements — Diseño

> Sub-proyecto del subdominio **Tarjetas de crédito** (capa de endpoints). Los tres endpoints "chicos" del
> staging: ver (`GET`), descartar (`DELETE`) y reconocer findings (`POST .../acknowledge`). Todos operan sobre
> la madre del usuario autenticado (uno por usuario, sin id en la ruta). El *qué* está en Notion → Endpoints →
> Tarjetas de crédito → `GET` / `DELETE` / `acknowledge`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** el recurso ya creado (`POST`/`PUT` de staging: router/service/schemas). Reusa
  `StagingStatementOut` y `StagingMadreOut`.
- **Cierre:** rama `feat/staging-credit-card-statements-chicos`, **squash-merge** a `main`.

---

## 1. Alcance

Agregar al recurso existente:
- `GET /credit-card-statements` — devuelve la madre + ítems del usuario (solo lectura).
- `DELETE /credit-card-statements` — borra la madre del usuario (ítems por cascade). 204.
- `POST /credit-card-statements/acknowledge` — limpia findings y deja `is_ready=true`.

**Fuera de alcance:** `promote`, endpoints de `credit-cards`.

---

## 2. Error code nuevo (`app/core/errors.py`)

| code | status | mensaje |
|---|---|---|
| `statement_has_no_findings` | 409 | `El resumen no tiene observaciones para reconocer.` |

Reusados: `not_found` (404).

---

## 3. GET /credit-card-statements

Solo lectura, sin escritura ni reviewer.

**Servicio `get_staging_statement(db, user) -> (StagingCreditCard, list[StagingCreditCardItem])`:**
1. Buscar la madre del usuario (`staging_credit_cards` por `user_id`). Si no → 404 `not_found`.
2. Leer sus `staging_credit_card_items`.

**Response 200 `StagingStatementOut`** (madre con `review_findings`/`is_ready` **tal como están persistidos** —
no se re-corre el reviewer — + `items[]` con `missing_fields` al vuelo). No se exponen `reviewed_at` /
`user_acknowledged_at`.

---

## 4. DELETE /credit-card-statements

Hard-delete simple, una transacción.

**Servicio `delete_staging_statement(db, user) -> None`:**
1. Buscar la madre del usuario. Si no → 404 `not_found`.
2. `db.delete(madre)` (los ítems se van por `ON DELETE CASCADE`). `commit`.

No se toca ninguna tabla definitiva (el staging nunca se materializó en `cash_flow_entries`).

**Response 204** sin body.

---

## 5. POST /credit-card-statements/acknowledge

Body vacío (`{}`). Una transacción; UPDATE puntual sobre 3 columnas de la madre.

**Servicio `acknowledge_staging_statement(db, user) -> StagingCreditCard`:**
1. Buscar la madre del usuario. Si no → 404 `not_found`.
2. Si `madre.review_findings == '[]'` → 409 `statement_has_no_findings`.
3. UPDATE: `review_findings='[]'`, `user_acknowledged_at=now`, `is_ready=true`. **No** se tocan `reviewed_at`
   ni `updated_at`. **No** se re-corre el reviewer ni ningún motor.

**Preservar `updated_at`:** como `onupdate=func.now()` bumpea `updated_at` en cualquier UPDATE del ORM, se usa
un `update(StagingCreditCard).values(..., updated_at=madre.updated_at)` de Core (setea explícito el valor
actual) — mismo patrón que `acknowledge_obligation`. Luego `db.refresh(madre)`.

**Response 200 `StagingMadreOut`** (sin ítems; `review_findings: []`, `is_ready: true`).

---

## 6. Decisiones, con su porqué

- **GET no escribe ni revisa:** el reviewer corre en POST/PUT; el GET sólo devuelve el estado persistido.
  `missing_fields` sí se deriva al vuelo (no es columna).
- **DELETE hard, sin condiciones:** el staging es transitorio y no tiene historia financiera (nada
  materializado). A diferencia de `DELETE /credit-cards/{id}`, no hay soft-delete ni chequeo de pagos.
- **Acknowledge preserva `updated_at`:** reconocer no es cambio de negocio (Regla de updated_at); por eso el
  UPDATE de Core fija `updated_at` a su valor actual en vez de dejar que el `onupdate` lo bumpee.
- **Acknowledge no dispara motor:** la madre del staging no materializa; `is_ready=true` solo habilita el
  `promote` (futuro sub-proyecto).
- **Todos por pertenencia al token:** sin id en la ruta; la madre/ítems son del usuario autenticado.

---

## 7. Tests (extender `tests/test_credit_card_statements.py`)

Reusar `cc_catalog`, `_auth`, `_payload`, `_post_staging`.

**GET:**
- **200:** POST → GET → 200, misma forma (madre + `items[]` con `missing_fields`); `id` coincide con el del
  POST.
- **404:** GET sin staging → 404 `not_found`.
- **Refleja los PUT:** POST → PUT madre (completar) → GET → la madre trae los valores actualizados.
- **No re-revisa:** GET no cambia `review_findings`/`is_ready` respecto del estado persistido (dos GET seguidos
  devuelven lo mismo).

**DELETE:**
- **204:** POST → DELETE → 204; GET posterior → 404 (se borró); un nuevo POST funciona (queda sin staging).
- **404:** DELETE sin staging → 404 `not_found`.

**acknowledge:**
- **200:** POST (deja findings, p.ej. `new_card` sin tarjeta) → acknowledge → 200, `review_findings == []`,
  `is_ready is True`, sin `items` en el body.
- **404:** acknowledge sin staging → 404.
- **409:** acknowledge dos veces — el segundo, con `review_findings` ya en `[]`, → 409
  `statement_has_no_findings`.
- **No re-revisa:** tras acknowledge, un GET sigue mostrando `review_findings == []` / `is_ready true` (el
  acknowledge no re-corre el reviewer que volvería a poner `new_card`).

**401:** los tres endpoints sin token → 401.

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/staging-credit-card-statements-chicos`), TDD:
1. Code nuevo en `errors.py`.
2. Tests (rojo) → 3 funciones de servicio + 3 endpoints en el router (verde) → commit.
3. Suite completa verde → cierre.
