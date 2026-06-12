# PlanningEngine: saldar deuda abierta con el excedente ocioso

Fecha: 2026-06-12
Estado: aprobado (diseño)
Extiende: `docs/superpowers/specs/2026-06-11-planning-engine-design.md`

## Problema

El PlanningEngine hoy **excluye** la `deuda_abierta` de sus decisiones: solo
netea los pagos manuales de deuda abierta contra la capacity del mes (los resta),
pero **no genera pagos** para saldar el resto. Resultado: cuando el plan deja
excedente, ese excedente **se acumula como balance** indefinidamente en vez de
ir bajando la deuda abierta pendiente.

Queremos que el motor vuelque el **excedente ocioso** de cada mes a saldar la
deuda abierta, generando `CashFlowPayment` auto-generados, hasta cancelarla.

## Contexto del motor (lo que ya hace)

`app/services/planning/engine.py`, `run_planning` simula mes a mes. Por mes:
`capacity = available + pending_income − remaining − open_debt_committed`, y
`_allocate_month` decide en 3 pasos: (1) obligatorios sin tasa al 100%,
(2) mínimos garantizados, (3) avalancha por tasa descendente con **look-ahead
M+1** (`_lookahead_reserve`, retiene para demanda con tasa > 2× del mes
siguiente). El sobrante `capacity − _spent` se vuelve `prev_balance` y **se
arrastra** al mes siguiente. `_materialize` crea los `CashFlowPayment` auto.

La `deuda_abierta` es una `cash_flow_entry` **sin `event_date`, sin tasas, sin
mínimo** (0% de interés). Sus pagos (manuales o auto) se agrupan por mes en el
CTE `open_debt_monthly` del timeline y se ven como gasto de ese mes.

## Decisiones tomadas (brainstorming)

- **Última prioridad.** El repago de deuda abierta es un **paso 4** que corre
  después de obligatorios, mínimos, avalancha y la retención del look-ahead.
  Solo usa plata que de otro modo quedaría ociosa (0% → es lo último que conviene
  pagar).
- **Todo el ocioso, hasta saldar.** Vuelca todo el excedente ocioso del mes,
  con tope en el saldo pendiente de la deuda.
- **Más vieja primero.** Si hay varias deudas abiertas (todas 0%), se saldan por
  antigüedad.
- **Horizonte M+1.** Se respeta la miopía actual del motor: solo se mira el mes
  siguiente. Limitación aceptada y documentada (ver abajo).
- **`planned_date` = último día del mes.** El ocioso se conoce al cierre del mes;
  datarlo el último día es lo más correcto y es neutro para el bucketing mensual.

## Definición de "ocioso" (lo importante)

El sobrante de un mes **no** es todo ocioso: hoy se arrastra como balance y M+1
puede necesitarlo para sus **gastos normales** (sin tasa), no solo para deuda con
tasa. (Ej. real: junio-2026 deja 12.396 de sobrante, pero julio quedaría
−12.396 sin él → ese sobrante **no** es ocioso.)

Para el mes M, con `next` = entries de M+1:

```
sobrante_M = capacity_M − _spent(entries_M)          # lo que hoy es prev_balance
reserva_next = _reserve_next(entries_M, next, dial, open_debt_next)
ocioso_M = max(0, sobrante_M − reserva_next)
```

`_reserve_next` = lo que M+1 necesita recibir arrastrado, calculado mirando M+1
(espejo de `_lookahead_reserve`, pero cubriendo también el faltante de caja, no
solo la demanda con tasa). Sea `s` el surplus standalone de M+1 (como lo computa
hoy `_lookahead_reserve` internamente: `pending_income(next) − dial −
open_debt_next −` Σ obligaciones no-tasa netas `−` Σ pisos de tasa netos), y
`rate_demand` la demanda con tasa > 0 de M+1:

```
reserva_next = max(0, rate_demand − max(0, s)) + max(0, −s)
```

- Si `s ≥ 0` (M+1 se sostiene solo): `reserva_next = max(0, rate_demand − s)`
  (idéntico al look-ahead actual con umbral 0).
- Si `s < 0` (M+1 tiene faltante): `reserva_next = rate_demand + (−s)` (se
  reserva el faltante de caja **y** la demanda con tasa).

Umbral 0: el 0% cede ante **cualquier** tasa futura. Verificación con datos
reales: junio→julio da `reserva_next = 12.396` → `ocioso_junio = 0` (no se barre);
el repago arranca en febrero-2027 y salda en mayo-2027.

## Paso 4: repago de la deuda abierta

En el loop mensual de `run_planning`, después de `_allocate_month` (y antes/junto
al cálculo de `prev_balance`):

1. `ocioso_M` según la fórmula de arriba.
2. Para cada deuda abierta del usuario, **ordenadas más vieja primero**:
   - `pendiente = monto − pagos_reales − pagos_manuales − autos_generados_hasta_ahora`
     (se trackea a lo largo de la simulación; arranca en `monto − real − manual`).
   - `pagar_conv = min(pendiente × fx, ocioso_restante)` (en base convertida).
   - `pagar_nativo = (pagar_conv / fx).quantize(0.01, ROUND_DOWN)`.
   - Si `pagar_nativo > 0`: registrar un pago auto (ver Materialización), restar
     de `pendiente` y de `ocioso_restante`.
   - Cortar cuando `ocioso_restante ≤ 0` o no quedan deudas con pendiente.
3. El total pagado **reduce el carry**: `prev_balance = sobrante_M − total_pagado`
   (la plata volcada deja de acumularse; lo retenido por `reserva_next` sigue
   arrastrándose).

`fx` de la deuda abierta = `_rate(db, currency_id, today)` (misma conversión que
usa el motor; la entry no tiene `event_date`, se usa la cotización de hoy).

## Carga de deudas abiertas y saldo

Al inicio de `run_planning` (junto a `_open_debt_committed`), cargar las
`cash_flow_entries` con `source_type = 'deuda_abierta'` del usuario:

- `monto` = `entry.amount`.
- `real` = Σ pagos con `plan_id IS NULL`.
- `manual` = Σ pagos con `plan_id = plan` y `is_auto_generated = false`.
- `pendiente_inicial = monto − real − manual` (si ≤ 0, la deuda ya está saldada
  → se ignora).
- Orden por antigüedad: `created_at` de la `cash_flow_entry`, desempate por
  `entry.id`. (No se joinea `obligations`: la entry de `deuda_abierta` no siempre
  tiene obligación asociada — el motor trabaja sobre la entry y sus pagos, igual
  que `_open_debt_committed`.)

`_open_debt_committed` (lo manual por mes que resta capacity) **no cambia**: los
235k manuales siguen restando capacity en sus meses. Los autos del paso 4 son
adicionales y se descuentan vía `prev_balance` (no se duplican).

## Materialización

Por cada pago auto del paso 4:

```python
CashFlowPayment(
    cash_flow_entry_id=<id de la deuda_abierta>,
    amount=pagar_nativo,
    plan_id=plan.id,
    planned_date=<último día del mes M>,
    is_auto_generated=True,
)
```

Se crean dentro del loop (no en `_materialize`, que recorre `_Entry`s; la deuda
abierta no es un `_Entry` del mes). El CTE `open_debt_monthly` del timeline los
agrupa por mes y los muestra como gasto.

## Idempotencia

Sin cambios: son `is_auto_generated=true`, así que `_delete_auto_payments` (que
corre al inicio de `run_planning` y en `clear_planning`) los borra y se regeneran
en cada corrida. Re-correr da el mismo resultado.

## Multi-moneda

La deuda abierta se paga en su propia moneda; el ocioso está en base convertida y
se convierte con el `fx` de la deuda (igual que la avalancha). El caso real es en
pesos.

## Limitación documentada (miopía M+1)

El paso 4 respeta el horizonte M+1 del motor: puede saldar el 0% aunque una deuda
**con tasa** 2+ meses después se hubiera beneficiado de retener esa plata
(quedaría arrastrándose y pagando más interés). Es la misma miopía ya documentada
en §10.1 del spec del motor. Aceptado para esta iteración.

## Tests

`tests/test_planning.py` (mismos fixtures/estilo):

1. **Ocioso real, no sobrante bruto:** un mes con sobrante pero cuyo M+1 tiene
   faltante de caja (gasto sin tasa) → **no** genera pago auto de deuda abierta
   (espejo de junio→julio).
2. **Barre cuando es ocioso:** meses self-sufficient → genera pagos auto que
   bajan la deuda; suma de autos = pendiente; queda saldada el mes esperado.
3. **Tope en el pendiente:** nunca paga más que `monto − real − manual`; el último
   pago es parcial.
4. **No toca manuales ni reales:** los pagos manuales/reales de la deuda abierta
   sobreviven; los autos son adicionales.
5. **Más vieja primero:** con dos deudas abiertas, se salda primero la más vieja.
6. **Idempotente:** re-correr borra y regenera los mismos autos; `clear_planning`
   los borra.
7. **Última prioridad:** si en M+1 hay demanda con tasa > 2×, se retiene para esa
   (no se vuelca al 0%).
8. **Multi-moneda:** deuda en USD se paga en USD, convirtiendo el ocioso.

## Touchpoints

| Archivo | Cambio |
|---|---|
| `app/services/planning/engine.py` | cargar deudas abiertas con `pendiente` y antigüedad; helper `_reserve_next` (extiende/reusa `_lookahead_reserve` exponiendo el `surplus` de M+1); paso 4 en el loop de `run_planning`; ajustar `prev_balance` por lo pagado |
| `tests/test_planning.py` | tests nuevos del paso 4 |

## Fuera de alcance (YAGNI)

- Escaneo de todo el futuro (M+2+) para reservar antes de saldar el 0%.
- Usar `priority_levels` para ordenar (orden = antigüedad).
- Buffer/colchón de efectivo (se vuelca todo el ocioso).
- Generar `plan_movements` (sigue siendo iteración futura del motor).
- Cambiar `clear_planning` o el formato de los endpoints.
