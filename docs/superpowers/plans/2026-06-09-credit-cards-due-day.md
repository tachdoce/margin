# credit_cards.due_day Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Agregar `due_day` a `credit_cards` (día de vencimiento, paralelo a `closing_day`) y que las
proyecciones del motor fechen el `event_date` en el vencimiento real, no en el cierre.

**Architecture:** Columna NOT NULL tras `closing_day` (editando la migración de creación + recrear DB de dev).
El promote la precarga al crear; el `CashFlowEngine.credit_cards` R2 la usa con heurística de mes
(due_day ≥ closing_day → mismo mes; si no → mes siguiente); editable por PATCH; expuesta en `CreditCardOut` y
la web. Reviewer sin cambios.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · pytest · Vue 3.

**Spec:** `docs/superpowers/specs/2026-06-09-credit-cards-due-day-design.md`

**Branch:** `feat/credit-cards-due-day` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## File Structure

| Archivo | Cambio |
|---|---|
| `backend/app/models/credit_card.py` | + `due_day` tras `closing_day` |
| `backend/alembic/versions/7e12cf8ac5e3_create_credit_card_tables.py` | + columna `due_day` tras `closing_day` en `credit_cards` |
| `backend/app/services/credit_card_statement_service.py` | promote create: setear `due_day`; PATCH: editar/validar `due_day` |
| `backend/app/services/cash_flow/credit_cards.py` | R2: `event_date` con `due_day` + heurística de mes |
| `backend/app/schemas/credit_card.py` | `CreditCardOut` + `CreditCardUpdate`: `due_day` |
| `backend/tests/test_credit_cards_model.py` | `_card_kwargs` + assert `due_day` |
| `backend/tests/test_cashflow_credit_cards.py` | actualizar/extender tests R2 |
| `backend/tests/test_promote_credit_card_statements.py` | assert `due_day` al promover |
| `backend/tests/test_credit_cards_mutations.py` | PATCH `due_day` |
| `backend/tests/test_credit_cards_read.py` | assert `due_day` en GET |
| `web/src/pages/CreditCards.vue` | mostrar + editar `due_day` |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/credit-cards-due-day
```

---

## Task 1: Columna `due_day` (modelo + migración + recrear DB)

**Files:**
- Modify: `backend/app/models/credit_card.py`
- Modify: `backend/alembic/versions/7e12cf8ac5e3_create_credit_card_tables.py`
- Modify: `backend/tests/test_credit_cards_model.py`

- [ ] **Step 1: Agregar `due_day` a `_card_kwargs` + assert (rojo)** en `tests/test_credit_cards_model.py`.
  En `_card_kwargs` (función helper, ~línea 11) agregar `due_day=13,` justo después de `closing_day=13,`. Y en
  `test_insert_and_read` agregar tras `assert card.closing_day == 13`:

```python
    assert card.due_day == 13
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_model.py -q
```

Expected: FALLA (`TypeError: 'due_day' is an invalid keyword argument for CreditCard`).

- [ ] **Step 3: Agregar la columna al modelo** `app/models/credit_card.py`, **inmediatamente después** de
  `closing_day`:

```python
    closing_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    due_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_model.py -q
```

- [ ] **Step 5: Editar la migración de creación** `alembic/versions/7e12cf8ac5e3_create_credit_card_tables.py`.
  En `op.create_table('credit_cards', ...)`, insertar la columna **justo después** de la de `closing_day`:

```python
    sa.Column('closing_day', sa.SmallInteger(), nullable=False),
    sa.Column('due_day', sa.SmallInteger(), nullable=False),
    sa.Column('financing_rate_local', sa.Numeric(precision=5, scale=2), nullable=False),
```

- [ ] **Step 6: Recrear la base de dev** (la columna es NOT NULL; la base se rehace vacía)

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic downgrade base && alembic upgrade head
```

Expected: baja y vuelve a subir sin error (las migraciones de seed se re-aplican).

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/credit_card.py alembic/versions/7e12cf8ac5e3_create_credit_card_tables.py tests/test_credit_cards_model.py && git commit -m "feat: columna credit_cards.due_day"
```

---

## Task 2: Promote precarga `due_day`

**Files:**
- Modify: `backend/app/services/credit_card_statement_service.py`
- Test: `backend/tests/test_promote_credit_card_statements.py`

- [ ] **Step 1: Assert en el test del promote de tarjeta nueva (rojo)**. En
  `test_promote_new_card` (`tests/test_promote_credit_card_statements.py`), tras obtener la `card` creada,
  agregar (el `_seed_ready_staging` usa `due_date=date(2026, 5, 25)`):

```python
    assert card.due_day == 25  # del día de staging.due_date
```

> Si el test no tiene la `card` en una variable, obtenerla:
> `card = _cards(db_session, user)[0]` (helper ya existente) antes del assert.

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_promote_credit_card_statements.py::test_promote_new_card -q
```

Expected: FALLA (al crear la tarjeta sin `due_day` el INSERT viola NOT NULL → error; o el assert falla).

- [ ] **Step 3: Setear `due_day` en la rama de creación** del promote
  (`app/services/credit_card_statement_service.py`), junto a `closing_day`:

```python
            closing_day=madre.closing_date.day,
            due_day=madre.due_date.day,
```

(Solo en la rama `if is_new:`. En la rama de actualización **no** se toca `due_day`, igual que `closing_day`.)

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_promote_credit_card_statements.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/credit_card_statement_service.py tests/test_promote_credit_card_statements.py && git commit -m "feat: promote precarga credit_cards.due_day"
```

---

## Task 3: Motor R2 — `event_date` por `due_day` (heurística de mes)

**Files:**
- Modify: `backend/app/services/cash_flow/credit_cards.py`
- Test: `backend/tests/test_cashflow_credit_cards.py`

- [ ] **Step 1: Actualizar/extender los tests R2 (rojo).** En `tests/test_cashflow_credit_cards.py`:

(a) **Reemplazar** `test_closing_day_clamped_in_projection` (hoy usa `closing_day=31` y espera día 30) por una
versión que clampea el **due_day** (con `due_day >= closing_day` para que sea el mismo mes):

```python
def test_due_day_clamped_in_projection(db_session, user_uy, sub_type):
    card = _make_card(db_session, user_uy, closing_day=13, due_day=31)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("69.99"), currency_id=1, item_type_id=sub_type)
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 6, 30))
    # due_day 31 en junio (30 días) -> último día del mes
    assert _by_key(db_session, card)[(2026, 6, 1)].event_date == date(2026, 6, 30)
```

(b) **Agregar** dos tests de la heurística:

```python
def test_projection_due_day_same_month(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13, due_day=25)  # 25 >= 13 -> mismo mes
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("100.00"), currency_id=1, item_type_id=1,
              current_installment=3, total_installments=4)  # falta 1 cuota -> junio
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    assert _by_key(db_session, card)[(2026, 6, 1)].event_date == date(2026, 6, 25)


def test_projection_due_day_next_month(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=28, due_day=5)  # 5 < 28 -> mes siguiente
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("100.00"), currency_id=1, item_type_id=1,
              current_installment=3, total_installments=4)  # cierre proyectado junio -> vence julio
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    entry = _by_key(db_session, card)[(2026, 6, 1)]  # issue = mes de cierre (junio)
    assert entry.event_date == date(2026, 7, 5)       # vence el mes siguiente
```

> Los tests existentes `test_pending_installment_projects_remaining_months` y
> `test_subscription_projects_every_month` siguen pasando: `_card_kwargs` trae `due_day=13 == closing_day=13`,
> así que el `event_date` proyectado sigue siendo el día 13 del mes de cierre (heurística "mismo mes").

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py -q
```

Expected: FALLAN los nuevos `test_projection_due_day_*` y `test_due_day_clamped_in_projection` (el motor sigue
usando `closing_day`).

- [ ] **Step 3: Cambiar el `event_date` en R2** (`app/services/cash_flow/credit_cards.py`, bloque
  "Responsabilidad 2"). Reemplazar:

```python
        for (y, m, cid), amount in _projection_sums(db, statement, horizon).items():
            fin, over = rate_pair.get(cid, (None, None))
            targets[(y, m, cid)] = dict(
                event_date=compute_event_date(y, m, card.closing_day, False),
                amount=amount,
                financing_rate=fin,
                overdue_rate=over,
                minimum_payment=None,
            )
```

por:

```python
        for (y, m, cid), amount in _projection_sums(db, statement, horizon).items():
            fin, over = rate_pair.get(cid, (None, None))
            # vence el mismo mes del cierre si due_day >= closing_day; si no, el mes siguiente
            if card.due_day >= card.closing_day:
                dy, dm = y, m
            else:
                dy, dm = _add_months(y, m, 1)
            targets[(y, m, cid)] = dict(
                event_date=compute_event_date(dy, dm, card.due_day, False),
                amount=amount,
                financing_rate=fin,
                overdue_rate=over,
                minimum_payment=None,
            )
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow/credit_cards.py tests/test_cashflow_credit_cards.py && git commit -m "feat: CashFlowEngine R2 fecha el event_date con due_day"
```

---

## Task 4: PATCH edita `due_day`

**Files:**
- Modify: `backend/app/schemas/credit_card.py`
- Modify: `backend/app/services/credit_card_statement_service.py`
- Test: `backend/tests/test_credit_cards_mutations.py`

- [ ] **Step 1: Tests (rojo)** en `tests/test_credit_cards_mutations.py`:

```python
def test_patch_due_day_ok(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}", json={"due_day": 20}, headers=headers)
    assert r.status_code == 200
    assert r.json()["due_day"] == 20


def test_patch_due_day_invalid(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    assert client.patch(f"/credit-cards/{card.id}", json={"due_day": 0}, headers=headers).json()["code"] == "due_day_invalid"
    assert client.patch(f"/credit-cards/{card.id}", json={"due_day": 32}, headers=headers).json()["code"] == "due_day_invalid"
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_mutations.py -k due_day -q
```

Expected: FALLA (`due_day` no es campo de `CreditCardUpdate` → se ignora; el GET no trae `due_day` → KeyError, o el PATCH no cambia nada).

- [ ] **Step 3: Agregar `due_day` a `CreditCardUpdate`** (`app/schemas/credit_card.py`):

```python
class CreditCardUpdate(BaseModel):
    institution_id: int | None = None
    card_network_id: int | None = None
    closing_day: int | None = None
    due_day: int | None = None
```

- [ ] **Step 4: Validar y aplicar `due_day` en `update_credit_card`**
  (`app/services/credit_card_statement_service.py`). En el chequeo de `empty_patch`, sumar `due_day`:

```python
    if (
        payload.institution_id is None
        and payload.card_network_id is None
        and payload.closing_day is None
        and payload.due_day is None
    ):
        raise AppError(ErrorCode.empty_patch)
```

Tras la validación de `closing_day`, agregar la de `due_day`:

```python
    if payload.due_day is not None and not (1 <= payload.due_day <= 31):
        raise AppError(ErrorCode.due_day_invalid, field="due_day")
```

Y en el bloque de asignación (donde se setea `card.closing_day` si vino), agregar:

```python
    if payload.due_day is not None:
        card.due_day = payload.due_day
```

> `due_day_invalid` ya existe en `errors.py` (mensaje "El día de vencimiento debe estar entre 1 y 31.").

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_mutations.py -q
```

(Nota: estos tests asertan `r.json()["due_day"]`, que requiere la Task 5. Si corrés esta task antes que la 5,
agregá `due_day` a `CreditCardOut` ahora — o corré las tasks 4 y 5 juntas. Recomendado: hacer Task 5 en el
mismo commit.)

- [ ] **Step 6: Commit** (junto con Task 5, ver abajo).

---

## Task 5: Exponer `due_day` en `CreditCardOut`

**Files:**
- Modify: `backend/app/schemas/credit_card.py`
- Test: `backend/tests/test_credit_cards_read.py`

- [ ] **Step 1: Assert en GET (rojo)** en `tests/test_credit_cards_read.py::test_list_vigente_y_soft_deleted`
  (o un test de lista), tras obtener `cards`:

```python
    assert all("due_day" in c for c in cards)
```

- [ ] **Step 2: Agregar `due_day` a `CreditCardOut`** (`app/schemas/credit_card.py`): el campo y su mapeo en
  `from_model`, junto a `closing_day`:

```python
    closing_day: int
    due_day: int
```

```python
            closing_day=c.closing_day,
            due_day=c.due_day,
```

- [ ] **Step 3: Run → verde** (read + mutations)

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_read.py tests/test_credit_cards_mutations.py -q
```

- [ ] **Step 4: Commit** (Tasks 4 + 5)

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/schemas/credit_card.py app/services/credit_card_statement_service.py tests/test_credit_cards_mutations.py tests/test_credit_cards_read.py && git commit -m "feat: PATCH + CreditCardOut exponen credit_cards.due_day"
```

---

## Task 6: Web — mostrar y editar `due_day`

**Files:**
- Modify: `web/src/pages/CreditCards.vue`

- [ ] **Step 1: Mostrar el `due_day` en la fila de la tarjeta.** Reemplazar:

```html
          <span class="income-amount">cierra {{ card.closing_day }}</span>
```

por:

```html
          <span class="income-amount">cierra {{ card.closing_day }} · vence {{ card.due_day }}</span>
```

- [ ] **Step 2: Agregar `due_day` al form de edición inline.** Tras el `.field` de "Día de cierre":

```html
          <div class="field"><label>Día de cierre</label><input v-model="cardEdits[card.id].closing_day" type="number" min="1" max="31" /></div>
          <div class="field"><label>Día de vencimiento</label><input v-model="cardEdits[card.id].due_day" type="number" min="1" max="31" /></div>
```

- [ ] **Step 3: Incluir `due_day` en `startEditCard` y `saveCard`** (`<script setup>`):

En `startEditCard`:

```javascript
  cardEdits[card.id] = {
    institution_id: card.institution_id,
    card_network_id: card.card_network_id,
    closing_day: card.closing_day,
    due_day: card.due_day,
  }
```

En `saveCard`, agregar al body del `updateCreditCard`:

```javascript
      closing_day: Number(f.closing_day),
      due_day: Number(f.due_day),
```

- [ ] **Step 4: Verificar que compila**

```bash
cd /Users/tachone/proyectos/margin/web && npm run build
```

Expected: build sin errores.

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin && git add web/src/pages/CreditCards.vue && git commit -m "feat(web): mostrar y editar credit_cards.due_day"
```

---

## Task 7: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (444 previos, con los R2 actualizados + los nuevos de due_day).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/credit-cards-due-day` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** columna NOT NULL tras closing_day + migración editada + recrear DB (Task 1); promote
  precarga (Task 2); motor R2 heurística (Task 3); PATCH + due_day_invalid (Task 4); CreditCardOut + web (Tasks
  5–6); reviewer sin cambios (no hay task, correcto). ✓
- **Sin placeholders:** todo el código (modelo, migración, promote, motor, schemas, tests, web) está completo. ✓
- **Consistencia:** `due_day` smallint NOT NULL en modelo y migración (mismo orden, tras closing_day);
  `_card_kwargs` con `due_day=13`=`closing_day` mantiene verdes los tests R2 viejos; la heurística
  (`due_day >= closing_day`) y `_add_months` ya existente; `due_day_invalid` reusado; `CreditCardOut`/`Update`
  y la web alineadas. ✓
- **Orden de tasks:** las Tasks 4 y 5 se commitean juntas (los tests de PATCH leen `due_day` del response, que
  lo agrega la Task 5). Marcado explícito. ✓
