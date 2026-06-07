import calendar
from datetime import date, timedelta


def compute_event_date(year: int, month: int, target_day: int, shift_weekends: bool) -> date:
    """Fecha real de un evento del cronograma. Canónica de la familia CashFlowEngine.

    1. Clamp de fin de mes: si target_day excede los días del mes, usa el último día.
    2. Corrimiento de finde (solo si shift_weekends): si cae sábado/domingo, corre al lunes
       siguiente; si ese lunes cruza de mes, al viernes anterior. Nunca sale del mes objetivo.
    """
    last_day = calendar.monthrange(year, month)[1]
    day = min(target_day, last_day)
    result = date(year, month, day)

    if shift_weekends and result.weekday() >= 5:  # 5 = sábado, 6 = domingo
        monday = result + timedelta(days=7 - result.weekday())  # sáb->+2, dom->+1
        if monday.month == month:
            result = monday
        else:
            # el lunes cruzó de mes -> viernes anterior (sáb->-1, dom->-2)
            result = result - timedelta(days=result.weekday() - 4)

    return result
