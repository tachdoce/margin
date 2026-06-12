import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import AppError, ErrorCode
from app.models.cash_balance import CashBalance
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User
from app.models.currency import Currency
from app.models.currency_rate import CurrencyRate
from app.models.user_financial_settings import UserFinancialSettings
from app.services.planning import run_planning

TODAY = date(2026, 6, 15)


def _user(db_session):
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _plan(db_session, user, dial="0"):
    p = Plan(
        user_id=user.id, name="Plan", is_default=False, is_engine_generated=False,
        selected_at=datetime.now(timezone.utc), dial_amount=Decimal(dial), dial_currency_id=1,
    )
    db_session.add(p)
    db_session.flush()
    return p


def _cash(db_session, user, amount, currency_id=1):
    db_session.add(CashBalance(user_id=user.id, currency_id=currency_id, amount=Decimal(amount)))
    db_session.flush()


def _need(db_session, user, amount):
    db_session.add(UserFinancialSettings(user_id=user.id, monthly_need_amount=Decimal(amount)))
    db_session.flush()


def _entry(db_session, user, *, event_date, amount, source_type="gasto", is_income=False,
           currency_id=1, fin=None, over=None, minimum=None, source_id=None):
    e = CashFlowEntry(
        user_id=user.id, event_date=event_date, is_income=is_income, amount=Decimal(amount),
        currency_id=currency_id,
        financing_rate=None if fin is None else Decimal(fin),
        overdue_rate=None if over is None else Decimal(over),
        minimum_payment=None if minimum is None else Decimal(minimum),
        source_type=source_type, source_id=source_id or uuid.uuid4(),
    )
    db_session.add(e)
    db_session.flush()
    return e


def _pay(db_session, entry, amount, *, plan_id=None, planned_date=None, auto=False):
    p = CashFlowPayment(
        cash_flow_entry_id=entry.id, amount=Decimal(amount), plan_id=plan_id,
        planned_date=planned_date, is_auto_generated=auto,
    )
    db_session.add(p)
    db_session.flush()
    return p


def _autos(db_session, plan):
    return list(db_session.execute(
        select(CashFlowPayment)
        .where(CashFlowPayment.plan_id == plan.id, CashFlowPayment.is_auto_generated.is_(True))
        .order_by(CashFlowPayment.planned_date)
    ).scalars())


def _auto_for(db_session, plan, entry):
    return [a for a in _autos(db_session, plan) if a.cash_flow_entry_id == entry.id]


# --- esqueleto ---

def test_plan_not_found(db_session, seed_uy_currency):
    user = _user(db_session)
    with pytest.raises(AppError) as exc:
        run_planning(db_session, user, uuid.uuid4(), today=TODAY)
    assert exc.value.code == ErrorCode.not_found


def test_plan_of_other_user(db_session, seed_uy_currency):
    user = _user(db_session)
    other = _user(db_session)
    plan = _plan(db_session, other)
    with pytest.raises(AppError) as exc:
        run_planning(db_session, user, plan.id, today=TODAY)
    assert exc.value.code == ErrorCode.not_found


def test_empty_run_ok(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    run_planning(db_session, user, plan.id, today=TODAY)
    assert _autos(db_session, plan) == []


def test_endpoint_204_and_404(client, db_session, seed_uy_currency):
    token = client.post("/auth/register", json={"email": "p@x.com", "password": "12345678"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    user = db_session.execute(select(User)).scalars().all()[-1]
    plan = _plan(db_session, user)
    assert client.post(f"/plans/{plan.id}/planning", headers=headers).status_code == 204
    assert client.post(f"/plans/{uuid.uuid4()}/planning", headers=headers).status_code == 404


# --- población y exclusiones (el truco observable: un egreso con pago real parcial
# y decisión de pago total genera fila auto; si está excluido, no genera nada) ---

def test_gasto_incluido_con_real_parcial_genera_cap(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "10000")
    _need(db_session, user, "0")
    e = _entry(db_session, user, event_date=date(2026, 6, 20), amount="1000.00")
    _pay(db_session, e, "300.00")  # real parcial
    run_planning(db_session, user, plan.id, today=TODAY)
    autos = _autos(db_session, plan)
    assert len(autos) == 1
    assert autos[0].cash_flow_entry_id == e.id
    assert autos[0].amount == Decimal("1000.00")  # decisión total explícita (spec §8)
    assert autos[0].planned_date == date(2026, 6, 20)
    assert autos[0].is_auto_generated is True


def test_deuda_abierta_y_mes_pasado_excluidos(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "10000")
    _need(db_session, user, "0")
    abierta = _entry(db_session, user, event_date=None, amount="1000.00", source_type="deuda_abierta")
    pasada = _entry(db_session, user, event_date=date(2026, 5, 20), amount="1000.00")
    _pay(db_session, abierta, "300.00")
    _pay(db_session, pasada, "300.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    assert _autos(db_session, plan) == []


def test_plan_movement_de_otro_plan_excluido(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    otro = _plan(db_session, user)
    _cash(db_session, user, "10000")
    _need(db_session, user, "0")

    def _pm(p):
        pm = PlanMovement(
            plan_id=p.id, kind="deuda_informal", currency_id=1, principal_amount=Decimal("1000.00"),
            start_date=date(2026, 6, 20), rates_add_vat=False,
        )
        db_session.add(pm)
        db_session.flush()
        return pm

    mio = _entry(db_session, user, event_date=date(2026, 6, 20), amount="1000.00",
                 source_type="plan_movimiento", source_id=_pm(plan).id)
    ajeno = _entry(db_session, user, event_date=date(2026, 6, 20), amount="1000.00",
                   source_type="plan_movimiento", source_id=_pm(otro).id)
    _pay(db_session, mio, "300.00")
    _pay(db_session, ajeno, "300.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    autos = _autos(db_session, plan)
    assert [a.cash_flow_entry_id for a in autos] == [mio.id]


# --- pasos 1 y 2 ---

def test_minimos_se_pagan_aunque_quede_negativo(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="3000.00")  # gasto obligatorio
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="2000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="300.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    autos = _autos(db_session, plan)
    # gasto: pago total asumido, sin fila. Tarjeta: queda en el mínimo -> fila (capacity 0, sin paso 3)
    assert len(autos) == 1
    assert autos[0].cash_flow_entry_id == card.id
    assert autos[0].amount == Decimal("300.00")


def test_deuda_con_tasas_min_total_sin_fila(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="1000.00",
           source_type="deuda", fin="90.00", over="120.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # deuda con tasas: mínimo = total -> decidido == total sin pagos reales -> sin fila
    assert _autos(db_session, plan) == []


def test_manual_es_piso_y_no_genera_fila(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="1000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    _pay(db_session, card, "400.00", plan_id=plan.id, planned_date=date(2026, 6, 22))
    run_planning(db_session, user, plan.id, today=TODAY)
    # manual 400 cubre el mínimo y es la decisión exacta -> sin fila auto
    assert _autos(db_session, plan) == []


def _seed_usd(db_session):
    db_session.add(Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False,
                            allowed_in_credit_card=True))
    db_session.add(CurrencyRate(currency_id=3, rate_date=date(2026, 6, 22), value=Decimal("41")))
    db_session.flush()


# --- paso 3: avalancha ---

def test_alcanza_todo_cero_filas(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "50000")
    _need(db_session, user, "0")
    _entry(db_session, user, event_date=date(2026, 6, 20), amount="10000.00")  # gasto
    _entry(db_session, user, event_date=date(2026, 6, 22), amount="5000.00",
           source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="500.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # gasto total y tarjeta total sin pagos reales: el timeline ya asume pago total -> sin filas
    assert _autos(db_session, plan) == []


def test_avalancha_paga_tasa_mayor_primero_y_parcial(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "5200")
    _need(db_session, user, "0")
    cara = _entry(db_session, user, event_date=date(2026, 6, 20), amount="10000.00",
                  source_type="tarjeta_credito", fin="80.00", over="90.00", minimum="100.00")
    barata = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                    source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # capacity 5200; minimos 200; sobrante 5000 -> todo a la cara (80%)
    assert [a.amount for a in _auto_for(db_session, plan, cara)] == [Decimal("5100.00")]
    assert [a.amount for a in _auto_for(db_session, plan, barata)] == [Decimal("100.00")]


def test_capacity_usa_need_e_ingresos_pendientes(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "1000")
    _need(db_session, user, "600")
    _entry(db_session, user, event_date=date(2026, 6, 18), amount="4600.00",
           source_type="ingreso", is_income=True)
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # capacity = 1000 + 4600 - 600 = 5000 -> minimo 100 + 4900 extra
    assert [a.amount for a in _auto_for(db_session, plan, card)] == [Decimal("5000.00")]


def test_remaining_prorratea_dial_sin_settings(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user, dial="3000")
    _cash(db_session, user, "2000")
    # sin user_financial_settings -> dial prorrateado: junio 30 dias, hoy 16 -> 15 dias -> 1500
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    run_planning(db_session, user, plan.id, today=date(2026, 6, 16))
    # capacity = 2000 - 1500 = 500 -> minimo 100 + 400 extra
    assert [a.amount for a in _auto_for(db_session, plan, card)] == [Decimal("500.00")]


def test_cap_por_real_parcial_en_tarjeta(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "700")
    _need(db_session, user, "0")
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="1000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    _pay(db_session, card, "300.00")  # real parcial, cubre el minimo
    run_planning(db_session, user, plan.id, today=TODAY)
    # committed 300; sobrante 700 paga el saldo -> decidido 1000 == total con real parcial -> fila del total
    assert [a.amount for a in _auto_for(db_session, plan, card)] == [Decimal("1000.00")]


def test_multimoneda_paga_en_moneda_de_la_entry(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _seed_usd(db_session)
    _cash(db_session, user, "4000")
    _need(db_session, user, "0")
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="100.00", currency_id=3,
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="10.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # capacity 4000; minimo 10 USD consume 410; sobrante 3590 -> 3590/41 = 87.56 USD (ROUND_DOWN)
    assert [a.amount for a in _auto_for(db_session, plan, card)] == [Decimal("97.56")]


# --- deuda abierta: los manuales descuentan capacidad (espejo de open_debt_monthly) ---

def test_manual_de_deuda_abierta_descuenta_capacidad(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "10000")
    _need(db_session, user, "0")
    abierta = _entry(db_session, user, event_date=None, amount="20000.00", source_type="deuda_abierta")
    _pay(db_session, abierta, "4000.00", plan_id=plan.id, planned_date=date(2026, 6, 20))
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # capacity = 10000 - 4000 (manual de deuda abierta) = 6000 -> minimo 100 + 5900
    assert [a.amount for a in _auto_for(db_session, plan, card)] == [Decimal("6000.00")]


def test_manual_de_deuda_abierta_neteado_con_real_del_mes(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "10000")
    _need(db_session, user, "0")
    abierta = _entry(db_session, user, event_date=None, amount="20000.00", source_type="deuda_abierta")
    _pay(db_session, abierta, "4000.00", plan_id=plan.id, planned_date=date(2026, 6, 20))
    p = _pay(db_session, abierta, "4000.00")  # real del mes actual: ya salio del efectivo
    p.created_at = datetime(2026, 6, 16, tzinfo=timezone.utc)
    db_session.flush()
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="100.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # el real netea al planificado en su mes -> sin descuento -> la tarjeta se paga entera, sin fila
    assert _autos(db_session, plan) == []


# --- arrastre ---

def test_arrastre_de_tarjeta_al_mes_siguiente(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "100")
    _need(db_session, user, "0")
    card_id = uuid.uuid4()
    jun = _entry(db_session, user, event_date=date(2026, 6, 22), amount="1000.00",
                 source_type="tarjeta_credito", fin="120.00", over="240.00", minimum="100.00",
                 source_id=card_id)
    jul = _entry(db_session, user, event_date=date(2026, 7, 22), amount="0.00",
                 source_type="tarjeta_credito", fin="120.00", over="240.00", minimum="0.00",
                 source_id=card_id)
    run_planning(db_session, user, plan.id, today=TODAY)
    # junio: paga el minimo 100 (capacity 100). saldo 900, financiacion 120% -> interes
    # 900 * (120/100)/12 * 1.35 = 121.50 -> arrastra 1021.50 a julio.
    # julio: capacity 0 -> minimo 15% de 1021.50 = 153.23 (siempre, aunque negativo)
    assert [a.amount for a in _auto_for(db_session, plan, jun)] == [Decimal("100.00")]
    assert [a.amount for a in _auto_for(db_session, plan, jul)] == [Decimal("153.23")]
    assert _auto_for(db_session, plan, jul)[0].planned_date == date(2026, 7, 22)


# --- look-ahead 2X ---

def test_lookahead_retiene_para_tasa_futura_mayor_a_2x(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "5000")
    _need(db_session, user, "0")
    barata = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                    source_type="tarjeta_credito", fin="10.00", over="20.00", minimum="100.00")
    cara_jul = _entry(db_session, user, event_date=date(2026, 7, 22), amount="50000.00",
                      source_type="tarjeta_credito", fin="30.00", over="40.00", minimum="500.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # junio: sobrante 4900; candidata al 10% -> umbral 20%; julio tiene demanda al 30% (> 20)
    # sin fondear (surplus' de julio = -500) -> retiene todo: barata queda al minimo.
    assert [a.amount for a in _auto_for(db_session, plan, barata)] == [Decimal("100.00")]
    # julio: available 4900 -> minimo 500 + 4400 extra
    assert [a.amount for a in _auto_for(db_session, plan, cara_jul)] == [Decimal("4900.00")]


def test_lookahead_no_retiene_bajo_el_umbral(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "5000")
    _need(db_session, user, "0")
    actual = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                    source_type="tarjeta_credito", fin="10.00", over="20.00", minimum="100.00")
    futura = _entry(db_session, user, event_date=date(2026, 7, 22), amount="50000.00",
                    source_type="tarjeta_credito", fin="15.00", over="25.00", minimum="500.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # 15% < 2*10%: no se paga retener -> junio gasta el sobrante en la actual
    assert [a.amount for a in _auto_for(db_session, plan, actual)] == [Decimal("5000.00")]
    assert [a.amount for a in _auto_for(db_session, plan, futura)] == [Decimal("500.00")]


def test_lookahead_reserva_parcial_paga_el_resto_hoy(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "5000")
    _need(db_session, user, "0")
    barata = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                    source_type="tarjeta_credito", fin="10.00", over="20.00", minimum="100.00")
    cara_jul = _entry(db_session, user, event_date=date(2026, 7, 22), amount="2500.00",
                      source_type="tarjeta_credito", fin="30.00", over="40.00", minimum="500.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # junio: sobrante 4900; julio demanda cara = 2500 - 500 = 2000 sin fondear -> reserva 2000,
    # el resto (2900) va a la barata hoy: 100 + 2900 = 3000
    assert [a.amount for a in _auto_for(db_session, plan, barata)] == [Decimal("3000.00")]
    # julio: available 2000 -> minimo 500 + 1500 extra -> 2000 (parcial)
    assert [a.amount for a in _auto_for(db_session, plan, cara_jul)] == [Decimal("2000.00")]


def test_lookahead_umbral_exacto_2x_no_retiene(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "5000")
    _need(db_session, user, "0")
    actual = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                    source_type="tarjeta_credito", fin="10.00", over="20.00", minimum="100.00")
    futura = _entry(db_session, user, event_date=date(2026, 7, 22), amount="50000.00",
                    source_type="tarjeta_credito", fin="20.00", over="30.00", minimum="500.00")
    run_planning(db_session, user, plan.id, today=TODAY)
    # 20% == 2*10% exacto: la regla es estrictamente mayor -> no retiene
    assert [a.amount for a in _auto_for(db_session, plan, actual)] == [Decimal("5000.00")]
    assert [a.amount for a in _auto_for(db_session, plan, futura)] == [Decimal("500.00")]


def test_lookahead_descuenta_deuda_abierta_de_m1(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "5000")
    _need(db_session, user, "0")
    barata = _entry(db_session, user, event_date=date(2026, 6, 22), amount="10000.00",
                    source_type="tarjeta_credito", fin="10.00", over="20.00", minimum="100.00")
    _entry(db_session, user, event_date=date(2026, 7, 1), amount="3000.00",
           source_type="ingreso", is_income=True)
    cara_jul = _entry(db_session, user, event_date=date(2026, 7, 22), amount="1300.00",
                      source_type="tarjeta_credito", fin="30.00", over="40.00", minimum="500.00")
    abierta = _entry(db_session, user, event_date=None, amount="20000.00", source_type="deuda_abierta")
    _pay(db_session, abierta, "2500.00", plan_id=plan.id, planned_date=date(2026, 7, 10))
    run_planning(db_session, user, plan.id, today=TODAY)
    # julio standalone: ingresos 3000 - deuda abierta 2500 - minimo 500 = 0 -> demanda cara
    # sin fondear = 1300 - 500 = 800 -> junio reserva 800 y paga 100 + 4100 = 4200 a la barata.
    # (sin el descuento de deuda abierta, julio se autofinanciaria y junio pagaria 5000)
    assert [a.amount for a in _auto_for(db_session, plan, barata)] == [Decimal("4200.00")]
    # julio: available 800 + 3000 - 2500 = 1300 -> paga la tarjeta entera -> sin fila
    assert _auto_for(db_session, plan, cara_jul) == []


# --- regeneración ---

def test_arrastre_inicial_desde_mes_historico(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    card_id = uuid.uuid4()
    may = _entry(db_session, user, event_date=date(2026, 5, 22), amount="1000.00",
                 source_type="tarjeta_credito", fin="120.00", over="240.00", minimum="100.00",
                 source_id=card_id)
    _pay(db_session, may, "100.00")  # real: pago el minimo en mayo -> arrastra
    jun = _entry(db_session, user, event_date=date(2026, 6, 22), amount="0.00",
                 source_type="tarjeta_credito", fin="120.00", over="240.00", minimum="0.00",
                 source_id=card_id)
    run_planning(db_session, user, plan.id, today=TODAY)
    # mayo: saldo 900 al 120% -> interes 900*1.20/12*1.35 = 121.50 -> arrastra 1021.50 a junio
    # junio (capacity 0): minimo 15% de 1021.50 = 153.23 -> fila
    assert [a.amount for a in _auto_for(db_session, plan, jun)] == [Decimal("153.23")]


def test_recorrida_borra_solo_autos_y_es_idempotente(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="2000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="300.00")
    manual = _pay(db_session, card, "50.00", plan_id=plan.id, planned_date=date(2026, 6, 22))

    run_planning(db_session, user, plan.id, today=TODAY)
    primera = _autos(db_session, plan)
    primera_amounts = [a.amount for a in primera]
    primera_ids = [a.id for a in primera]
    run_planning(db_session, user, plan.id, today=TODAY)
    segunda = _autos(db_session, plan)

    # manual 50 < minimo 300 -> el motor completa: fila auto = 300 - 50 = 250
    assert primera_amounts == [Decimal("250.00")]
    assert [a.amount for a in segunda] == [Decimal("250.00")]
    assert primera_ids[0] != segunda[0].id  # regeneradas, no reusadas
    assert db_session.get(CashFlowPayment, manual.id) is not None  # el manual sobrevive
