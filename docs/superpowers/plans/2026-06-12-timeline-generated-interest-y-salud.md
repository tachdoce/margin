# Timeline: generated_interest + mes deuda sana + mes objetivo — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar a `get_timeline` tres salidas: `generated_interest` por mes (interés en pesos por pago parcial de tarjetas), `healthy_debt_month` y `goal_reached_month` (top-level).

**Architecture:** Se extrae la fórmula de interés de `monthly_carry` a `_raw_interest`/`monthly_interest` (sin cambiar la salida de `monthly_carry`). `get_timeline` acumula el interés por mes dentro de la cascada de carry que ya corre, lo expone en cada `MonthOut`, y al final deriva `healthy_debt_month` (de la serie de interés) y `goal_reached_month` (de los balances + el objetivo del plan). Solo tarjetas.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest. `Decimal` siempre.

**Spec:** `docs/superpowers/specs/2026-06-12-timeline-generated-interest-y-salud-design.md`

**Contexto base:**
- `cd backend && source .venv/bin/activate`; tests `pytest -q`.
- Sin migraciones (solo schema Pydantic + servicio).
- Para tarjetas, el timeline usa `cfe.financing_rate`, `cfe.overdue_rate`, `cfe.minimum_payment` **de la entry** (el JOIN a `credit_cards` es solo para el nombre). Por eso en los tests las tasas se setean en la `CashFlowEntry`, no en la card.

---

### Task 1: `monthly_interest` (refactor de interest.py)

**Files:**
- Modify: `app/services/cash_flow/interest.py`
- Create: `tests/test_interest.py`

- [ ] **Step 1: Escribir los tests**

Crear `tests/test_interest.py`:
```python
from decimal import Decimal

from app.services.cash_flow.interest import monthly_carry, monthly_interest


def test_monthly_interest_financiacion():
    # pago 200 >= mínimo 100 -> financiación 12%: saldo 800 * 0.12/12 * 1.35 = 10.80
    assert monthly_interest(Decimal("1000"), Decimal("200"), Decimal("100"),
                            Decimal("12"), Decimal("24")) == Decimal("10.80")


def test_monthly_interest_mora():
    # pago 50 < mínimo 100 -> mora 24%: saldo 950 * 0.24/12 * 1.35 = 25.65
    assert monthly_interest(Decimal("1000"), Decimal("50"), Decimal("100"),
                            Decimal("12"), Decimal("24")) == Decimal("25.65")


def test_monthly_interest_saldado():
    assert monthly_interest(Decimal("1000"), Decimal("1000"), Decimal("100"),
                            Decimal("12"), Decimal("24")) == Decimal("0.00")


def test_monthly_carry_sin_regresion():
    # comportamiento previo intacto: saldo 800 + interés 10.80 = 810.80
    assert monthly_carry(Decimal("1000"), Decimal("200"), Decimal("100"),
                         Decimal("12"), Decimal("24")) == Decimal("810.80")
```

- [ ] **Step 2: Correr (falla)**

Run: `pytest tests/test_interest.py -q`
Expected: FAIL (`monthly_interest` no existe).

- [ ] **Step 3: Refactorizar `interest.py`**

Reemplazar todo el cuerpo de `app/services/cash_flow/interest.py` por:
```python
from decimal import ROUND_HALF_UP, Decimal

from app.services.cash_flow.constants import HIDDEN_COST_FACTOR

Q = Decimal("0.01")


def _raw_interest(amount, payment, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """Interés (sin cuantizar) del saldo impago. 0 si está saldado.
    Financiación si el pago alcanzó el mínimo, mora si no."""
    balance = amount - payment
    if balance <= 0:
        return Decimal("0")
    paid_minimum = minimum_payment is not None and payment >= minimum_payment
    rate = financing_rate if paid_minimum else overdue_rate
    return balance * (rate / Decimal("100")) / Decimal("12") * HIDDEN_COST_FACTOR


def monthly_carry(amount, payment, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """Saldo impago + interés a arrastrar al mes siguiente (misma moneda). 0 si está saldado.

    Provisional: evolucionará. Tasa de financiación si el pago alcanzó el mínimo, mora si no.
    """
    balance = amount - payment
    if balance <= 0:
        return Decimal("0.00")
    interest = _raw_interest(amount, payment, minimum_payment, financing_rate, overdue_rate)
    return (balance + interest).quantize(Q, rounding=ROUND_HALF_UP)


def monthly_interest(amount, payment, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """El interés que el carry suma al mes siguiente, cuantizado (misma moneda). 0 si saldado."""
    return _raw_interest(amount, payment, minimum_payment, financing_rate, overdue_rate).quantize(
        Q, rounding=ROUND_HALF_UP
    )
```

- [ ] **Step 4: Correr (pasa)**

Run: `pytest tests/test_interest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/cash_flow/interest.py tests/test_interest.py
git commit -m "feat: monthly_interest (interés del carry expuesto); monthly_carry sin cambios"
```

---

### Task 2: campo `generated_interest` por mes

**Files:**
- Modify: `app/schemas/cash_flow_entry.py` (`MonthOut`)
- Modify: `app/services/cash_flow_entry_service.py` (import, cascada, armado de `MonthOut`)
- Test: `tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Escribir los tests**

En `tests/test_get_cash_flow_entries.py`, agregar al tope el import (junto a los demás `from app.models...`):
```python
from app.models.currency import Currency
from app.models.currency_rate import CurrencyRate
```
Y los tests (usan los helpers existentes `_headers`, `_last_user`, `_plan`, `_card`, `_pay`):
```python
def _june_card(db_session, user, card, *, amount, fin, over, minimum, currency_id=1):
    e = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 6, 29), is_income=False, amount=Decimal(amount),
        currency_id=currency_id, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal(fin), overdue_rate=Decimal(over), minimum_payment=Decimal(minimum),
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return e


def test_generated_interest_financiacion(client, db_session, seed_cc_refs):
    _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    e = _june_card(db_session, user, card, amount="1000.00", fin="12.00", over="24.00", minimum="100.00")
    _pay(db_session, e, amount="200.00", plan_id=plan.id, planned_date=date(2026, 6, 20))
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next(m for m in out.months if m.month == "2026-06")
    assert jun.generated_interest == Decimal("10.80")  # 800 * 0.12/12 * 1.35


def test_generated_interest_mora(client, db_session, seed_cc_refs):
    _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    e = _june_card(db_session, user, card, amount="1000.00", fin="12.00", over="24.00", minimum="100.00")
    _pay(db_session, e, amount="50.00", plan_id=plan.id, planned_date=date(2026, 6, 20))
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next(m for m in out.months if m.month == "2026-06")
    assert jun.generated_interest == Decimal("25.65")  # pago < mínimo -> mora 24%


def test_generated_interest_pagada_entera(client, db_session, seed_cc_refs):
    _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    _june_card(db_session, user, card, amount="1000.00", fin="12.00", over="24.00", minimum="100.00")
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))  # sin plan -> asume full
    jun = next(m for m in out.months if m.month == "2026-06")
    assert jun.generated_interest == Decimal("0.00")


def test_generated_interest_usd_convertido(client, db_session, seed_cc_refs):
    _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    db_session.add(Currency(id=3, country_code="UY", name="Dólar",
                            is_legal_tender=False, allowed_in_credit_card=True))
    db_session.add(CurrencyRate(currency_id=3, rate_date=date(2026, 6, 29), value=Decimal("40.00")))
    db_session.commit()
    e = _june_card(db_session, user, card, amount="100.00", fin="5.00", over="6.00",
                   minimum="10.00", currency_id=3)
    _pay(db_session, e, amount="20.00", plan_id=plan.id, planned_date=date(2026, 6, 20))
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next(m for m in out.months if m.month == "2026-06")
    # 80 * 0.05/12 * 1.35 = 0.45 USD * 40 = 18.00
    assert jun.generated_interest == Decimal("18.00")


def test_generated_interest_suma_varias_tarjetas(client, db_session, seed_cc_refs):
    _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    c1 = _card(db_session, user)
    c2 = _card(db_session, user)
    e1 = _june_card(db_session, user, c1, amount="1000.00", fin="12.00", over="24.00", minimum="100.00")
    e2 = _june_card(db_session, user, c2, amount="1000.00", fin="12.00", over="24.00", minimum="100.00")
    _pay(db_session, e1, amount="200.00", plan_id=plan.id, planned_date=date(2026, 6, 20))
    _pay(db_session, e2, amount="200.00", plan_id=plan.id, planned_date=date(2026, 6, 20))
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    jun = next(m for m in out.months if m.month == "2026-06")
    assert jun.generated_interest == Decimal("21.60")  # 10.80 * 2


def test_generated_interest_mes_pasado_cero(client, db_session, seed_cc_refs):
    _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    card = _card(db_session, user)
    e = CashFlowEntry(
        user_id=user.id, event_date=date(2026, 5, 29), is_income=False, amount=Decimal("1000.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("100.00"),
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    _pay(db_session, e, amount="200.00", plan_id=plan.id, planned_date=date(2026, 5, 20))
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    mayo = next(m for m in out.months if m.month == "2026-05")
    assert mayo.generated_interest == Decimal("0.00")  # histórico -> 0
```

- [ ] **Step 2: Correr (fallan)**

Run: `pytest tests/test_get_cash_flow_entries.py -q -k generated_interest`
Expected: FAIL (`MonthOut` no tiene `generated_interest`).

- [ ] **Step 3: Agregar el campo al schema**

En `app/schemas/cash_flow_entry.py`, en `MonthOut`, después de `balance: Decimal` agregar:
```python
    generated_interest: Decimal
```

- [ ] **Step 4: Acumular y exponer en `get_timeline`**

En `app/services/cash_flow_entry_service.py`:

(a) Import: cambiar
```python
from app.services.cash_flow.interest import monthly_carry
```
por
```python
from app.services.cash_flow.interest import monthly_carry, monthly_interest
```

(b) Inicializar el acumulador junto a `carry_in`/`min_override` (antes del `for serie in series.values():`):
```python
    generated_interest: dict = {}   # "YYYY-MM" -> interés generado ese mes (convertido)
```

(c) Dentro del loop de la serie, **antes** de `cin = monthly_carry(...)`, agregar:
```python
            interest = monthly_interest(amount, payment, minimum, r["financing_rate"], r["overdue_rate"])
            if interest > 0:
                mk = r["event_date"].strftime("%Y-%m")
                generated_interest[mk] = generated_interest.get(mk, Decimal("0")) + interest * _rate(
                    db, r["currency_id"], r["event_date"]
                )
            cin = monthly_carry(amount, payment, minimum, r["financing_rate"], r["overdue_rate"])
```

(d) En el armado de `MonthOut`, computar el valor por mes. Cambiar el bloque:
```python
        if key < current_key:
            # mes pasado: histórico, totales en 0, no arrastra
            available = pending_income = pending_expenses = remaining_spending = balance = Decimal("0")
        else:
```
por:
```python
        if key < current_key:
            # mes pasado: histórico, totales en 0, no arrastra
            available = pending_income = pending_expenses = remaining_spending = balance = Decimal("0")
            gen = Decimal("0")
        else:
            gen = generated_interest.get(key, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```
Y en el `MonthOut(...)`, agregar el campo:
```python
                balance=balance,
                generated_interest=gen,
```

- [ ] **Step 5: Correr (pasan)**

Run: `pytest tests/test_get_cash_flow_entries.py -q -k generated_interest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/schemas/cash_flow_entry.py app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py
git commit -m "feat: generated_interest por mes en el timeline (tarjetas)"
```

---

### Task 3: `healthy_debt_month` y `goal_reached_month`

**Files:**
- Modify: `app/schemas/cash_flow_entry.py` (`TimelineOut`)
- Modify: `app/services/cash_flow_entry_service.py` (helpers + derivación + return)
- Test: `tests/test_get_cash_flow_entries.py`

- [ ] **Step 1: Escribir los tests**

En `tests/test_get_cash_flow_entries.py`, agregar imports al tope:
```python
from app.schemas.cash_flow_entry import MonthOut
from app.services.cash_flow_entry_service import _healthy_debt_month, _goal_reached_month
```
Y los tests:
```python
_Z = Decimal("0")


def _mo(key, *, balance="0", gen="0"):
    return MonthOut(
        month=key, available=_Z, pending_income=_Z, pending_expenses=_Z, remaining_spending=_Z,
        balance=Decimal(balance), incomes=[], expenses=[], generated_interest=Decimal(gen),
    )


def test_healthy_despues_del_ultimo_interes():
    months = [_mo("2026-06", gen="10"), _mo("2026-07", gen="5"), _mo("2026-08", gen="0"), _mo("2026-09", gen="0")]
    assert _healthy_debt_month(months, "2026-06") == "2026-08"


def test_healthy_nunca_en_horizonte():
    months = [_mo("2026-06", gen="10"), _mo("2026-07", gen="5")]  # interés hasta el último mes
    assert _healthy_debt_month(months, "2026-06") is None


def test_healthy_ya_sano_desde_el_arranque():
    months = [_mo("2026-06", gen="0"), _mo("2026-07", gen="0")]
    assert _healthy_debt_month(months, "2026-06") == "2026-06"


def test_goal_alcanzado_despues_de_sano():
    months = [_mo("2026-06", balance="100", gen="10"), _mo("2026-07", balance="600", gen="0"),
              _mo("2026-08", balance="1200", gen="0")]
    # healthy = 2026-07; objetivo 1000 -> primer mes >= 07 con balance >= 1000 = 2026-08
    assert _goal_reached_month(months, "2026-06", "2026-07", Decimal("1000")) == "2026-08"


def test_goal_balance_antes_de_sano_no_cuenta():
    months = [_mo("2026-06", balance="5000", gen="10"), _mo("2026-07", balance="600", gen="0")]
    # 5000 >= 1000 en junio pero junio < healthy 2026-07; julio 600 < 1000 -> None
    assert _goal_reached_month(months, "2026-06", "2026-07", Decimal("1000")) is None


def test_goal_sin_objetivo():
    months = [_mo("2026-06", balance="5000", gen="0")]
    assert _goal_reached_month(months, "2026-06", "2026-06", None) is None


def test_goal_healthy_null():
    months = [_mo("2026-06", balance="5000", gen="10")]
    assert _goal_reached_month(months, "2026-06", None, Decimal("1000")) is None


def test_timeline_expone_healthy_y_goal(client, db_session, seed_cc_refs):
    _headers(client)
    user = _last_user(db_session)
    plan = _plan(db_session, user)
    plan.goal_kind = "ahorro_total"
    plan.goal_amount = Decimal("5.00")
    plan.goal_currency_id = 1
    db_session.commit()
    _income_entry(db_session, user, plan, event_date=date(2026, 6, 5), amount="50000.00")  # balance +
    card = _card(db_session, user)
    jun = _june_card(db_session, user, card, amount="1000.00", fin="12.00", over="24.00", minimum="100.00")
    _pay(db_session, jun, amount="200.00", plan_id=plan.id, planned_date=date(2026, 6, 20))  # interés en junio
    db_session.add(CashFlowEntry(  # julio: recibe el carry, sin plan -> asume full -> interés 0
        user_id=user.id, event_date=date(2026, 7, 29), is_income=False, amount=Decimal("0.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=card.id,
        financing_rate=Decimal("12.00"), overdue_rate=Decimal("24.00"), minimum_payment=Decimal("0.00"),
    ))
    db_session.commit()
    out = svc.get_timeline(db_session, user, plan.id, today=date(2026, 6, 10))
    assert out.healthy_debt_month == "2026-07"   # interés en junio, 0 en julio
    assert out.goal_reached_month == "2026-07"    # primer mes sano con balance >= 5
```

- [ ] **Step 2: Correr (fallan)**

Run: `pytest tests/test_get_cash_flow_entries.py -q -k "healthy or goal or timeline_expone"`
Expected: FAIL (`_healthy_debt_month` / `_goal_reached_month` no existen; `TimelineOut` sin campos).

- [ ] **Step 3: Campos en `TimelineOut`**

En `app/schemas/cash_flow_entry.py`, en `TimelineOut`, agregar:
```python
class TimelineOut(BaseModel):
    months: list[MonthOut]
    open_debts: list[TimelineEntryOut]
    healthy_debt_month: str | None = None
    goal_reached_month: str | None = None
```

- [ ] **Step 4: Helpers de derivación**

En `app/services/cash_flow_entry_service.py`, agregar a nivel módulo (antes de `get_timeline`):
```python
def _healthy_debt_month(months: list[MonthOut], current_key: str) -> str | None:
    """Mes tras el último con generated_interest > 0 (entre los meses activos). None si el
    interés llega hasta el final del horizonte; primer mes activo si nunca hubo interés."""
    active = [m for m in months if m.month >= current_key]
    if not active:
        return None
    last = None
    for i, m in enumerate(active):
        if m.generated_interest > 0:
            last = i
    if last is None:
        return active[0].month
    if last + 1 >= len(active):
        return None
    return active[last + 1].month


def _goal_reached_month(
    months: list[MonthOut], current_key: str, healthy_month: str | None, goal_local: Decimal | None
) -> str | None:
    """Primer mes activo >= healthy_month con balance >= goal_local. None si no hay objetivo,
    no hay deuda sana, o no se alcanza."""
    if healthy_month is None or goal_local is None:
        return None
    for m in months:
        if m.month < current_key:
            continue
        if m.month >= healthy_month and m.balance >= goal_local:
            return m.month
    return None
```

- [ ] **Step 5: Derivar y devolver en `get_timeline`**

Reemplazar la última línea:
```python
    return TimelineOut(months=months, open_debts=[e for e in open_debts if e.amount != 0])
```
por:
```python
    healthy_month = _healthy_debt_month(months, current_key)
    goal_local = None
    if plan.goal_amount is not None and plan.goal_currency_id is not None:
        goal_local = plan.goal_amount * _rate(db, plan.goal_currency_id, today)
    goal_month = _goal_reached_month(months, current_key, healthy_month, goal_local)
    return TimelineOut(
        months=months,
        open_debts=[e for e in open_debts if e.amount != 0],
        healthy_debt_month=healthy_month,
        goal_reached_month=goal_month,
    )
```

- [ ] **Step 6: Correr (pasan) + suite del timeline**

Run: `pytest tests/test_get_cash_flow_entries.py -q`
Expected: PASS (nuevos + existentes).

- [ ] **Step 7: Commit**

```bash
git add app/schemas/cash_flow_entry.py app/services/cash_flow_entry_service.py tests/test_get_cash_flow_entries.py
git commit -m "feat: healthy_debt_month y goal_reached_month en el timeline"
```

---

### Task 4: Cierre

- [ ] **Step 1: Suite completa verde**

Run: `pytest -q`
Expected: PASS (toda la suite).

- [ ] **Step 2: Squash-merge a main**

```bash
git checkout main
git merge --squash feat/timeline-generated-interest
git commit -m "$(cat <<'EOF'
feat: timeline expone generated_interest, healthy_debt_month y goal_reached_month

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Borrar la rama (tras squash va -D)**

```bash
git branch -D feat/timeline-generated-interest
```

- [ ] **Step 4: Push**

```bash
git push
```

- [ ] **Step 5: Migraciones Alembic**

Esta feature **no agregó migraciones** (solo schema Pydantic + servicio), así que no hay cadena que verificar. (Si hubiera: confirmar `alembic heads` = 1 sola y lineal con main antes del push.)
