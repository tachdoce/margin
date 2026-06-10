# CashFlowEngine.credit_cards — relleno mensual con amount 0 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans o
> superpowers:subagent-driven-development. Steps con checkbox (`- [ ]`).

**Goal:** R2 del motor de tarjetas densifica la proyección: cada mes M+1→horizonte, en local **y** USD, tiene
una entry; donde no hay cuota, `amount = 0`.

**Architecture:** Helper `_densify_projection` que rellena con 0 las claves `(año, mes, moneda)` faltantes sobre
el dict de `_projection_sums`; el loop de R2 queda igual (recorre un dict denso). No toca R1, `_reconcile`, ni el
soft-delete (que borra futuros aparte, en `delete_credit_card`).

**Tech Stack:** SQLAlchemy 2.0 · Decimal · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-credit-card-monthly-zero-fill-design.md`

**Branch:** `feat/credit-card-monthly-zero-fill`. Squash-merge al final. **No Notion. Sin web.**

**Higiene:** `cd .../backend && source .venv/bin/activate && pytest -q` (sin pipes/`2>&1`). Git planos. No push.

**Estado actual (verificado):** R2 hace `for (y, m, cid), amount in _projection_sums(db, statement, horizon).items():`.
`_projection_sums` devuelve solo claves con monto > 0, base = `statement.closing_date`, cota
`(horizon.year, horizon.month)`, usa `_add_months`. `materialize_credit_card` tiene `local_id`/`usd_id` en
scope. `Decimal` y `_add_months` ya importados. `HORIZON = date(2027, 12, 31)`. Tests en
`tests/test_cashflow_credit_cards.py` (`TODAY = date(2026, 5, 1)`, helper `_by_key`).

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/credit-card-monthly-zero-fill
```

---

## Task 1: Relleno denso en R2 (TDD)

**Files:** `app/services/cash_flow/credit_cards.py`, `tests/test_cashflow_credit_cards.py`

- [ ] **Step 1: Test nuevo (rojo)** — agregar a `tests/test_cashflow_credit_cards.py`:

```python
def test_projection_zero_fills_both_currencies(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))  # solo local en R1
    _add_item(db_session, st, amount=Decimal("100.00"), currency_id=1, item_type_id=1,
              current_installment=3, total_installments=4)  # 1 cuota -> junio
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 8, 31))
    keys = _by_key(db_session, card)
    for (y, m) in [(2026, 6), (2026, 7), (2026, 8)]:        # cada mes M+1..horizonte en ambas monedas
        assert (y, m, 1) in keys and (y, m, 3) in keys
    assert keys[(2026, 6, 1)].amount == Decimal("100.00")  # cuota real
    assert keys[(2026, 7, 1)].amount == Decimal("0")       # local sin cuota -> 0
    assert keys[(2026, 6, 3)].amount == Decimal("0")       # usd siempre -> 0
    assert keys[(2026, 7, 1)].financing_rate == keys[(2026, 6, 1)].financing_rate  # tasas heredadas
    assert keys[(2026, 7, 1)].minimum_payment == Decimal("0.00")                    # 0 * 0.15
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py::test_projection_zero_fills_both_currencies -q
```

Expected: FALLA (hoy los meses sin cuota / la moneda USD no existen).

- [ ] **Step 3: Helper `_densify_projection`** — en `app/services/cash_flow/credit_cards.py`, agregar después de
  `_projection_sums`:

```python
def _densify_projection(sums, statement, horizon, currency_ids):
    """Rellena con 0 cada (año, mes, moneda) faltante desde M+1 hasta el horizonte (in place)."""
    base_y, base_m = statement.closing_date.year, statement.closing_date.month
    horizon_key = (horizon.year, horizon.month)
    k = 1
    while True:
        y, m = _add_months(base_y, base_m, k)
        if (y, m) > horizon_key:
            break
        for cid in currency_ids:
            sums.setdefault((y, m, cid), Decimal("0"))
        k += 1
    return sums
```

- [ ] **Step 4: Usar el helper en R2** — en `materialize_credit_card`, reemplazar:

```python
        for (y, m, cid), amount in _projection_sums(db, statement, horizon).items():
```

por:

```python
        sums = _projection_sums(db, statement, horizon)
        _densify_projection(sums, statement, horizon, (local_id, usd_id))
        for (y, m, cid), amount in sums.items():
```

(El cuerpo del loop —cálculo de `event_date`, `minimum_payment = amount * PROJECTED_MINIMUM_RATE`, etc.— queda
**igual**.)

- [ ] **Step 5: Run el test nuevo → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py::test_projection_zero_fills_both_currencies -q
```

Expected: PASS.

- [ ] **Step 6: Commit (implementación)**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow/credit_cards.py tests/test_cashflow_credit_cards.py && git commit -m "feat: motor de tarjetas rellena cada mes con amount 0 hasta el horizonte"
```

---

## Task 2: Actualizar los tests que asumen proyección rala

**Files:** `tests/test_cashflow_credit_cards.py`

Cada cambio refleja la semántica nueva: dentro de M+1→horizonte, los meses/monedas sin cuota **existen con
`amount = 0`** (no faltan). El mes del cierre (M) sigue siendo solo R1 (el relleno arranca en M+1).

- [ ] **Step 1: `test_zero_usd_total_only_local`** — reemplazar el cuerpo desde `entries = ...`:

```python
    keys = _by_key(db_session, card)
    assert (2026, 5, 1) in keys       # R1 local (mes del cierre)
    assert (2026, 5, 3) not in keys   # R1 no crea USD con total 0; el relleno arranca en M+1
```

- [ ] **Step 2: `test_reconcile_updates_not_duplicates`** — reemplazar las 2 últimas líneas (`assert len... / assert entries[0]...`):

```python
    keys_list = [(e.issue_year, e.issue_month, e.currency_id) for e in _orm_entries(db_session, card)]
    assert sum(1 for k in keys_list if k == (2026, 5, 1)) == 1   # no se duplicó
    assert _by_key(db_session, card)[(2026, 5, 1)].amount == Decimal("200.00")
```

- [ ] **Step 3: `test_currency_that_lost_total_is_deleted`** — reemplazar las 2 últimas líneas
  (`cids = ... / assert cids == {1}`):

```python
    keys = _by_key(db_session, card)
    assert (2026, 5, 3) not in keys                      # la fila USD del cierre (R1) se borró al caer el total
    assert keys[(2026, 6, 3)].amount == Decimal("0")     # el USD futuro queda como relleno 0
```

- [ ] **Step 4: `test_pending_installment_projects_remaining_months`** — reemplazar
  `assert (2026, 7, 1) not in keys  # no hay más cuotas` por:

```python
    assert keys[(2026, 7, 1)].amount == Decimal("0")  # relleno: meses sin cuota quedan en 0
```

- [ ] **Step 5: `test_one_payment_not_projected`** — reemplazar las 2 últimas líneas (`future = ... / assert future == []`):

```python
    keys = _by_key(db_session, card)
    future = [k for k in keys if (k[0], k[1]) != (2026, 5)]
    assert future  # ahora hay relleno hasta el horizonte
    assert all(keys[k].amount == Decimal("0") for k in future)  # nada real proyectado (compra de un pago)
```

- [ ] **Step 6: `test_reprojection_deletes_stale_future`** — reemplazar la última línea
  (`assert (2026, 6, 1) not in keys and (2026, 7, 1) not in keys ...`) por:

```python
    assert keys[(2026, 6, 1)].amount == Decimal("0") and keys[(2026, 7, 1)].amount == Decimal("0")  # sin cuota -> 0 (no se borran; el borrado de futuros es del soft-delete)
```

- [ ] **Step 7: Run el archivo completo → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py -q
```

Expected: PASS. Si algún otro test del archivo falla por el relleno (p. ej. cuenta entries o asume ausencia de
un mes/moneda dentro de M+1→horizonte), aplicar el mismo criterio: el mes/moneda ahora existe con `amount = 0`.
Los tests de tasas/mínimo de R1, `test_no_delete_when_real_payment` (invariante de pago real) y
`test_past_entry_not_touched` (mes pasado, fuera del relleno) no deberían cambiar.

- [ ] **Step 8: Commit (tests)**

```bash
cd /Users/tachone/proyectos/margin/backend && git add tests/test_cashflow_credit_cards.py && git commit -m "test: ajustar tests de tarjetas a la proyección densa (futuros sin cuota = 0)"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde. (Atención a `test_get_cash_flow_entries.py` y a los tests del servicio de tarjetas
—soft-delete/restore— por si alguno asumía la proyección rala; aplicar el mismo criterio si hace falta.)

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: superpowers:finishing-a-development-branch. **squash-merge** a
  `main` (1 commit). Push **manual**. Sin Notion.

---

## Self-Review

- **Cobertura del spec:** §1 densificar (Task 1 Steps 3-4); §2 valores de las filas 0 (heredados del loop, sin
  cambios); §3 helper (Step 3); §5 tests del relleno (Step 1) + ajuste de los que asumían ausencia (Task 2);
  §6 consecuencias asumidas. ✓
- **Placeholder scan:** sin TBD/TODO; helper y todos los reemplazos de test escritos con su valor. ✓
- **Consistencia:** `_densify_projection` definido (Step 3) y usado (Step 4); `setdefault` no pisa los montos
  reales; `local_id`/`usd_id` en scope. El soft-delete (borrado de futuros) vive en `delete_credit_card` y no
  pasa por el motor → no se toca. ✓
- **Semántica de borrado:** re-proyección de tarjeta activa ⇒ futuros sin cuota quedan en 0 (Steps 4, 6); el
  borrado de futuros real es del soft-delete (fuera de alcance, intacto). ✓
