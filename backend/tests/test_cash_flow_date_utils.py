from datetime import date

from app.services.cash_flow.date_utils import compute_event_date


def test_clamp_fin_de_mes_febrero():
    # día 31 en febrero no bisiesto -> 28
    assert compute_event_date(2026, 2, 31, False) == date(2026, 2, 28)


def test_clamp_fin_de_mes_bisiesto():
    # día 31 en febrero bisiesto -> 29
    assert compute_event_date(2024, 2, 31, False) == date(2024, 2, 29)


def test_shift_sabado_a_lunes():
    # 2026-08-15 es sábado -> lunes 2026-08-17
    assert date(2026, 8, 15).weekday() == 5
    assert compute_event_date(2026, 8, 15, True) == date(2026, 8, 17)


def test_shift_domingo_a_lunes():
    # 2026-08-16 es domingo -> lunes 2026-08-17
    assert date(2026, 8, 16).weekday() == 6
    assert compute_event_date(2026, 8, 16, True) == date(2026, 8, 17)


def test_shift_lunes_cruza_mes_a_viernes_anterior():
    # 2025-05-31 es sábado; el lunes siguiente (2025-06-02) cruza de mes -> viernes anterior 2025-05-30
    assert date(2025, 5, 31).weekday() == 5
    assert compute_event_date(2025, 5, 31, True) == date(2025, 5, 30)


def test_sin_shift_queda_literal():
    # sábado sin shift_weekends queda en su día (solo aplica el clamp)
    assert compute_event_date(2026, 8, 15, False) == date(2026, 8, 15)
