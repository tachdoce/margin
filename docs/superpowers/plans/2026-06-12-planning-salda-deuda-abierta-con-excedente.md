# PlanningEngine salda deuda abierta con excedente — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que `run_planning` vuelque el excedente ocioso de cada mes a saldar la(s) deuda(s) abierta(s), generando `CashFlowPayment` auto-generados, hasta cancelarlas — más vieja primero, respetando lo que M+1 necesita.

**Architecture:** Un "paso 4" en el loop mensual de `run_planning`, después de la asignación de los 3 pasos actuales. Se calcula el ocioso = `sobrante − reserva_M+1` (reserva = faltante de caja de M+1 + demanda con tasa, vía un refactor del look-ahead que expone sus términos), y se vuelca a las deudas abiertas (cargadas con su saldo pendiente al inicio). Los pagos son `is_auto_generated=true`, así que la limpieza/idempotencia existente los cubre.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, pytest. `Decimal` siempre.

**Spec:** `docs/superpowers/specs/2026-06-12-planning-salda-deuda-abierta-con-excedente-design.md`

**Contexto base:**
- `cd backend && source .venv/bin/activate`; tests `pytest -q` (base `margin_test`, `create_all` + fixtures).
- Todo el cambio es en `app/services/planning/engine.py` y `tests/test_planning.py`.
- `Q = Decimal("0.01")`, `ZERO = Decimal("0")`, `ROUND_DOWN`, `calendar`, `date`, `dataclass`, `CashFlowEntry`, `CashFlowPayment`, `_rate`, `_payment_sums`, `_spent`, `_pending_income`, `_carry_preview` ya están importados/definidos en el módulo.

---

### Task 1: Refactor del look-ahead — exponer (demand, surplus) y `_reserve_next`

Cambio **behavior-preserving** de `_lookahead_reserve` (los tests de look-ahead existentes lo blindan), más el helper nuevo `_reserve_next`.

**Files:**
- Modify: `app/services/planning/engine.py` (función `_lookahead_reserve`, ~líneas 264-292)
- Test: `tests/test_planning.py` (correr los existentes)

- [ ] **Step 1: Correr los tests de look-ahead (verde antes del refactor)**

Run: `pytest tests/test_planning.py -q -k lookahead`
Expected: PASS (todos los `test_lookahead_*` pasan).

- [ ] **Step 2: Reemplazar `_lookahead_reserve` por la versión refactorizada + `_reserve_next`**

Reemplazar toda la función `_lookahead_reserve` por estas tres funciones:
```python
def _lookahead_terms(
    entries: list[_Entry], next_entries: list[_Entry], threshold: Decimal, dial: Decimal,
    open_debt_next: Decimal = ZERO,
) -> tuple[Decimal, Decimal]:
    """(demand, surplus) de M+1: demand = monto con tasa > threshold por encima del floor;
    surplus = caja standalone de M+1 antes de la avalancha discrecional (puede ser < 0)."""
    if not next_entries:
        return ZERO, ZERO
    carry = _carry_preview(entries)
    saved = [(n, n.carry_in) for n in next_entries]
    try:
        for n in next_entries:
            if n.is_card:
                n.carry_in += carry.get((n.source_id, n.currency_id), ZERO)
        surplus = _pending_income(next_entries) - dial - open_debt_next
        demand = ZERO
        for n in next_entries:
            if n.is_income or n.amount <= 0:
                continue
            if not n.has_rates:
                surplus -= max(ZERO, n.amount - n.paid_real) * n.fx
                continue
            floor = max(n.committed, min(n.minimum, n.amount))
            surplus -= max(ZERO, floor - n.paid_real) * n.fx
            if n.financing_rate > threshold:
                demand += max(ZERO, n.amount - floor) * n.fx
        return demand, surplus
    finally:
        for n, cin in saved:
            n.carry_in = cin


def _lookahead_reserve(
    entries: list[_Entry], next_entries: list[_Entry], threshold: Decimal, dial: Decimal,
    open_debt_next: Decimal = ZERO,
) -> Decimal:
    demand, surplus = _lookahead_terms(entries, next_entries, threshold, dial, open_debt_next)
    return max(ZERO, demand - max(ZERO, surplus))


def _reserve_next(
    entries: list[_Entry], next_entries: list[_Entry], dial: Decimal, open_debt_next: Decimal
) -> Decimal:
    """Lo que M+1 necesita recibir arrastrado para sostenerse: faltante de caja + demanda
    con tasa (umbral 0: el 0% de la deuda abierta cede ante cualquier tasa futura)."""
    demand, surplus = _lookahead_terms(entries, next_entries, ZERO, dial, open_debt_next)
    return max(ZERO, demand - max(ZERO, surplus)) + max(ZERO, -surplus)
```

- [ ] **Step 3: Correr los tests de look-ahead (siguen verde)**

Run: `pytest tests/test_planning.py -q -k lookahead`
Expected: PASS (sin cambios de comportamiento).

- [ ] **Step 4: Commit**

```bash
git add app/services/planning/engine.py
git commit -m "refactor(planning): expone términos del look-ahead y agrega _reserve_next"
```

---

### Task 2: Paso 4 — saldar deuda abierta con el ocioso

**Files:**
- Modify: `app/services/planning/engine.py` (nuevos `_OpenDebt`, `_load_open_debts`, `_last_day`, `_sweep_open_debts`; paso 4 en `run_planning`)
- Test: `tests/test_planning.py`

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_planning.py`, agregar (usan los helpers existentes `_user`, `_plan`, `_cash`, `_need`, `_entry`, `_pay`, `_autos`, `_auto_for`):
```python
# --- deuda abierta: el excedente ocioso la salda ---

def test_excedente_ocioso_salda_deuda_abierta(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="50000.00",
           source_type="ingreso", is_income=True)
    abierta = _entry(db_session, user, event_date=None, amount="30000.00", source_type="deuda_abierta")
    run_planning(db_session, user, plan.id, today=TODAY)
    autos = _auto_for(db_session, plan, abierta)
    assert [a.amount for a in autos] == [Decimal("30000.00")]
    assert autos[0].planned_date == date(2026, 6, 30)  # último día del mes


def test_open_debt_resta_los_manuales_del_pendiente(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="50000.00",
           source_type="ingreso", is_income=True)
    abierta = _entry(db_session, user, event_date=None, amount="30000.00", source_type="deuda_abierta")
    _pay(db_session, abierta, "10000.00", plan_id=plan.id, planned_date=date(2026, 6, 5))  # manual
    run_planning(db_session, user, plan.id, today=TODAY)
    # pendiente = 30000 - 10000 manual = 20000; el auto cubre solo eso
    assert [a.amount for a in _auto_for(db_session, plan, abierta)] == [Decimal("20000.00")]
    # el pago manual sobrevive intacto
    manuales = db_session.execute(
        select(CashFlowPayment).where(
            CashFlowPayment.cash_flow_entry_id == abierta.id,
            CashFlowPayment.is_auto_generated.is_(False),
        )
    ).scalars().all()
    assert [p.amount for p in manuales] == [Decimal("10000.00")]


def test_sobrante_necesario_para_mes_siguiente_no_se_barre(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    # junio deja 50k, pero julio (gasto sin tasa 50k, sin ingreso) lo necesita entero
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="50000.00",
           source_type="ingreso", is_income=True)
    _entry(db_session, user, event_date=date(2026, 7, 10), amount="50000.00", source_type="gasto")
    abierta = _entry(db_session, user, event_date=None, amount="30000.00", source_type="deuda_abierta")
    run_planning(db_session, user, plan.id, today=TODAY)
    assert _auto_for(db_session, plan, abierta) == []


def test_salda_en_varios_meses_ultimo_parcial(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    # junio y julio cada uno deja 50k ocioso (julio se sostiene solo); deuda 70k
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="50000.00",
           source_type="ingreso", is_income=True)
    _entry(db_session, user, event_date=date(2026, 7, 20), amount="50000.00",
           source_type="ingreso", is_income=True)
    abierta = _entry(db_session, user, event_date=None, amount="70000.00", source_type="deuda_abierta")
    run_planning(db_session, user, plan.id, today=TODAY)
    autos = _auto_for(db_session, plan, abierta)
    assert [a.amount for a in autos] == [Decimal("50000.00"), Decimal("20000.00")]
    assert [a.planned_date for a in autos] == [date(2026, 6, 30), date(2026, 7, 31)]


def test_deuda_mas_vieja_primero(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="15000.00",
           source_type="ingreso", is_income=True)
    vieja = _entry(db_session, user, event_date=None, amount="10000.00", source_type="deuda_abierta")
    vieja.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    nueva = _entry(db_session, user, event_date=None, amount="10000.00", source_type="deuda_abierta")
    nueva.created_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    db_session.flush()
    run_planning(db_session, user, plan.id, today=TODAY)
    assert [a.amount for a in _auto_for(db_session, plan, vieja)] == [Decimal("10000.00")]
    assert [a.amount for a in _auto_for(db_session, plan, nueva)] == [Decimal("5000.00")]


def test_retiene_para_tasa_futura_sobre_deuda_abierta(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    # junio deja 50k; julio tiene una tarjeta con tasa y demanda -> se retiene, no se barre el 0%
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="50000.00",
           source_type="ingreso", is_income=True)
    _entry(db_session, user, event_date=date(2026, 7, 22), amount="50000.00",
           source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    abierta = _entry(db_session, user, event_date=None, amount="30000.00", source_type="deuda_abierta")
    run_planning(db_session, user, plan.id, today=TODAY)
    assert _auto_for(db_session, plan, abierta) == []


def test_open_debt_autos_idempotentes_y_clear(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="50000.00",
           source_type="ingreso", is_income=True)
    abierta = _entry(db_session, user, event_date=None, amount="30000.00", source_type="deuda_abierta")
    run_planning(db_session, user, plan.id, today=TODAY)
    run_planning(db_session, user, plan.id, today=TODAY)  # idempotente
    assert [a.amount for a in _auto_for(db_session, plan, abierta)] == [Decimal("30000.00")]
    clear_planning(db_session, user, plan.id)
    assert _auto_for(db_session, plan, abierta) == []


def test_open_debt_en_usd_convierte(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    db_session.add(Currency(id=3, country_code="UY", name="Dólar",
                            is_legal_tender=False, allowed_in_credit_card=True))
    db_session.add(CurrencyRate(currency_id=3, rate_date=TODAY, value=Decimal("40.00")))
    db_session.flush()
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="50000.00",
           source_type="ingreso", is_income=True)
    abierta = _entry(db_session, user, event_date=None, amount="100.00",
                     source_type="deuda_abierta", currency_id=3)
    run_planning(db_session, user, plan.id, today=TODAY)
    # 100 USD * 40 = 4000 pesos de ocioso -> paga 100 USD
    assert [a.amount for a in _auto_for(db_session, plan, abierta)] == [Decimal("100.00")]
```

- [ ] **Step 2: Correr (fallan)**

Run: `pytest tests/test_planning.py -q -k "ocioso or manuales or sobrante_necesario or salda_en_varios or mas_vieja or retiene_para_tasa or idempotentes_y_clear or usd_convierte"`
Expected: FAIL (el motor todavía no salda deuda abierta).

- [ ] **Step 3: Agregar `_OpenDebt`, `_load_open_debts`, `_last_day`, `_sweep_open_debts`**

En `app/services/planning/engine.py`, después de `_open_debt_committed` (o junto a los demás helpers), agregar:
```python
@dataclass
class _OpenDebt:
    entry_id: uuid.UUID
    fx: Decimal
    outstanding: Decimal  # en moneda nativa de la deuda


def _load_open_debts(db: Session, user: User, plan: Plan, today: date) -> list[_OpenDebt]:
    """Deudas abiertas del usuario con saldo pendiente (monto − real − manual), más vieja
    primero. No se joinea obligations (la entry puede no tenerla)."""
    rows = list(
        db.execute(
            select(CashFlowEntry)
            .where(
                CashFlowEntry.user_id == user.id,
                CashFlowEntry.source_type == "deuda_abierta",
            )
            .order_by(CashFlowEntry.created_at.asc(), CashFlowEntry.id.asc())
        ).scalars()
    )
    if not rows:
        return []
    paid, manual = _payment_sums(db, [r.id for r in rows], plan)
    debts: list[_OpenDebt] = []
    for r in rows:
        outstanding = r.amount - paid.get(r.id, ZERO) - manual.get(r.id, ZERO)
        if outstanding <= 0:
            continue
        debts.append(_OpenDebt(entry_id=r.id, fx=_rate(db, r.currency_id, today), outstanding=outstanding))
    return debts


def _last_day(month: tuple[int, int]) -> date:
    y, m = month
    return date(y, m, calendar.monthrange(y, m)[1])


def _sweep_open_debts(
    db: Session, plan: Plan, open_debts: list[_OpenDebt], idle: Decimal, month: tuple[int, int]
) -> Decimal:
    """Vuelca `idle` (base convertida) a las deudas abiertas (más vieja primero), generando
    pagos auto datados el último día del mes. Devuelve el total pagado (base convertida)."""
    if idle <= 0:
        return ZERO
    planned = _last_day(month)
    total = ZERO
    for d in open_debts:
        if idle <= 0:
            break
        if d.outstanding <= 0:
            continue
        pay_conv = min(d.outstanding * d.fx, idle)
        pay_native = (pay_conv / d.fx).quantize(Q, rounding=ROUND_DOWN)
        if pay_native <= 0:
            continue
        db.add(
            CashFlowPayment(
                cash_flow_entry_id=d.entry_id, amount=pay_native, plan_id=plan.id,
                planned_date=planned, is_auto_generated=True,
            )
        )
        d.outstanding -= pay_native
        spent = pay_native * d.fx
        idle -= spent
        total += spent
    return total
```

- [ ] **Step 4: Insertar el paso 4 en `run_planning`**

En `run_planning`, después de `open_debt = _open_debt_committed(db, user, plan, month_start)`, agregar la carga:
```python
    open_debt_balances = _load_open_debts(db, user, plan, today)
```
Y dentro del loop, reemplazar:
```python
        _allocate_month(month_entries, capacity, next_entries, dial, open_debt_next)
        prev_balance = capacity - _spent(month_entries)
        _apply_carry(month_entries, next_entries)
```
por:
```python
        _allocate_month(month_entries, capacity, next_entries, dial, open_debt_next)
        sobrante = capacity - _spent(month_entries)
        reserva = _reserve_next(month_entries, next_entries, dial, open_debt_next)
        idle = max(ZERO, sobrante - reserva)
        paid_open = _sweep_open_debts(db, plan, open_debt_balances, idle, m)
        prev_balance = sobrante - paid_open
        _apply_carry(month_entries, next_entries)
```

- [ ] **Step 5: Correr los tests nuevos (pasan)**

Run: `pytest tests/test_planning.py -q -k "ocioso or manuales or sobrante_necesario or salda_en_varios or mas_vieja or retiene_para_tasa or idempotentes_y_clear or usd_convierte"`
Expected: PASS.

- [ ] **Step 6: Correr toda la suite de planning + el resto**

Run: `pytest tests/test_planning.py -q && pytest -q`
Expected: PASS (los 32 tests previos siguen verdes + los 7 nuevos).

- [ ] **Step 7: Commit**

```bash
git add app/services/planning/engine.py tests/test_planning.py
git commit -m "feat(planning): salda deuda abierta con el excedente ocioso"
```

---

## Notas de cierre

- Verificación manual opcional sobre el plan real (Estabilización): correr `POST /plans/{id}/planning` y revisar en el timeline que la deuda abierta de 300k quede saldada hacia may-2027 (los 65k restantes cubiertos feb→may).
- El spec y el plan los commitea la tab de diseño; cada task de este plan commitea su código.
