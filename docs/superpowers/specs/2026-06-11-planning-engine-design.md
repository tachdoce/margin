# PlanningEngine v1 — diseño

Fecha: 2026-06-11

## Contexto y objetivo

El **PlanningEngine** es el motor que decide *qué pagar, cuánto y cuándo* dentro de un plan.
Dado un plan elegido, intenta pagar el máximo de todos los egresos; cuando la plata no alcanza,
deja impago (total o parcialmente) lo que menos interés/mora genere, para arrastrar la menor
deuda posible al mes siguiente.

Es una etapa previa e independiente del **CashFlowEngine**: el CashFlowEngine materializa
`cash_flow_entries` (la realidad proyectada); el PlanningEngine lee esa realidad y genera
`cash_flow_payments` planificados (`is_auto_generated = true`). En v1 **no** crea
`plan_movements` (préstamos/financings quedan para una iteración futura).

## Alcance v1

- Genera solo `cash_flow_payments` auto-generados.
- Decide sobre todo el horizonte: mes a mes desde el mes actual hasta el último mes con entries,
  arrastrando el balance de cada mes al siguiente.
- Estrategia: avalancha (tasa descendente) con look-ahead de un mes (umbral `2·X`, ver §6.4).

Fuera de alcance (documentado en §10): tomar préstamos, look-ahead multi-mes, proyección de
tipo de cambio, arrastre de egresos que no son tarjeta.

## 1. Contrato

`POST /plans/{plan_id}/planning` (auth requerida).

- Plan inexistente o de otro usuario → `not_found` (404).
- La corrida:
  1. Borra todos los `cash_flow_payments` del plan con `is_auto_generated = true`.
  2. Simula mes a mes (§6) y crea los pagos nuevos.
  3. Todo en una transacción: un único commit al final; si algo falla no queda el plan a medio borrar.
- Sin entries futuras → corrida válida: 0 pagos.

Respuesta: `204 No Content`. El Planning corre desde la pantalla de Flujo de caja: cuando el
endpoint devuelve OK, el front re-pide `GET /cash-flow-entries` (timeline) y ahí se ve el
resultado (pagos planificados, balances, meses en rojo). No se duplica esa información en una
respuesta propia.

El servicio vive en `app/services/planning/` (paquete nuevo, hermano de `cash_flow/`), con
`today` inyectable como en `materialize_credit_card`. El router `plans.py` solo delega.

## 2. Población

La misma que el timeline (`get_timeline`), con dos exclusiones:

- **Entra:** entries de `gasto`, `deuda`, `ingreso`, `tarjeta_credito`, y
  `plan_movimiento` / `plan_movimiento_entrada` **solo del plan elegido**.
- **Queda afuera:**
  - `deuda_abierta` (sin `event_date`; el usuario la paga a mano con pagos manuales).
  - Meses anteriores al mes actual (histórico: no se planifica).
  - Entries con monto efectivo 0 (p. ej. fila de moneda sin deuda).

Por cada entry se carga: monto, tasas (`financing_rate`, `overdue_rate`), `minimum_payment`,
pagos reales (`plan_id IS NULL`), pagos planificados manuales del plan
(`plan_id = X AND is_auto_generated = false`).

Conversión de moneda: `currency_rates` a la fecha del `event_date` (fallback 1), y a la fecha
de hoy para el efectivo inicial — igual que el timeline. Sin proyección de tipo de cambio.

## 3. Capacidad del mes

La misma matemática que `get_timeline`:

- **Mes actual:** `available` = cash balances convertidos a hoy; `remaining_spending` =
  `monthly_need` del usuario, o el dial prorrateado por días restantes si no hay settings.
- **Meses siguientes:** `available` = balance del mes anterior; `remaining_spending` = dial completo.
- `capacity = available + ingresos_pendientes − remaining_spending`.

Ingreso pendiente de una entry de ingreso = efectivo − pagos reales, donde
efectivo = planificado manual si > 0, si no el monto (regla `_effective_planned`).

Los pagos planificados manuales del plan sobre deudas abiertas (excluidas de la decisión,
§2) sí descuentan capacidad en el mes de su `planned_date`, neteados contra los pagos
reales del mismo mes — espejo del bloque `open_debt_monthly` del timeline.

## 4. Compromisos previos (lo que el motor no decide)

Para cada egreso, el **compromiso previo** es:

> el planificado manual si > 0; si no, los pagos reales si > 0; si no, 0.

(Espejo de `_effective_planned` y de la cascada del timeline: el manual es la intención total,
el real es su ejecución.)

- Los pagos manuales son decisiones del usuario: el motor los respeta como piso, descuenta su
  plata de la capacidad y solo puede **agregar** por encima (nunca reducir).
- Los pagos reales ya salieron del efectivo (`available` los refleja); el consumo de capacidad
  de una entry es `decidido − pagos_reales` (piso 0).

## 5. Categorías de egresos

| Categoría | Definición | Tratamiento |
|---|---|---|
| **Obligatorios** | `financing_rate` y `overdue_rate` nulas o 0 (gastos, deudas sin tasas, plan_movements sin tasas) | Pago total, siempre — aunque la capacidad quede negativa |
| **Deudas con tasas** | `deuda` / `plan_movimiento` con tasas; su `minimum_payment` en el timeline es el total | Se pagan enteras en el paso de mínimos — aunque dé negativo |
| **Tarjetas** | `tarjeta_credito`; tienen `minimum_payment` real y tasas | Mínimo garantizado; el resto compite por tasa (§6.3–6.4) |

Mínimo de tarjeta: el `minimum_payment` de la entry; si la entry tiene arrastre del propio
motor (§7), se recalcula al 15 % del monto efectivo (`PROJECTED_MINIMUM_RATE`, regla del
timeline). Los compromisos previos cuentan para el mínimo (si el real o el manual ya lo cubren,
no se agrega nada).

## 6. Algoritmo de asignación (por mes, en orden)

Estado inicial: `decidido(entry) = compromiso previo`. `sobrante = capacity − consumo de los
compromisos manuales`.

### 6.1 Paso 1 — obligatorios

`decidido = monto efectivo` para todos los obligatorios. Se ejecuta siempre, aunque el
sobrante quede negativo.

### 6.2 Paso 2 — mínimos

Para deudas con tasas y tarjetas: `decidido = max(decidido, mínimo)`. Siempre, aunque dé
negativo. Si después de este paso el sobrante es ≤ 0, el mes termina acá: el balance queda
negativo y arrastra al mes siguiente (el rojo se ve en el timeline).

### 6.3 Paso 3 — avalancha

Candidatas: entries con tasas y saldo (`monto efectivo − decidido`) > 0, ordenadas por
`financing_rate` **descendente** (desempate: `event_date` asc, `id` asc). Se usa la tasa de
financiación porque el mínimo ya está cubierto (no hay mora en juego).

Para cada candidata se paga el saldo completo (convertido); la última puede quedar parcial.
Este paso nunca deja el sobrante negativo.

Justificación (avalancha): cada peso extra ahorra `tasa/12` de interés — el ahorro marginal
depende solo de la tasa, no del tamaño de la deuda.

### 6.4 Look-ahead de un mes (umbral `2·X`)

Antes de asignarle sobrante a la candidata con tasa `X`, el motor mira M+1:

1. Proyecta M+1 **standalone** (sin el sobrante de M): `surplus' = ingresos(M+1) − dial −
   deudas abiertas comprometidas de M+1 (§3) − obligatorios(M+1) − mínimos(M+1)`, con los montos de M+1 incluyendo los arrastres derivados
   de las decisiones de M tomadas hasta este punto (los saldos aún no asignados arrastran como
   impagos con mínimo cubierto).
2. Demanda cara no fondeada: `R = max(0, Σ saldos de candidatas de M+1 con tasa > 2·X − max(0, surplus'))`.
   (Las tasas > 2·X son las primeras que la avalancha local de M+1 fondearía, por eso la resta directa.)
3. Reserva `min(sobrante, R)` — esa plata no se asigna a `X` y queda en el balance de M.
   Lo que no se reserva se asigna normalmente.

Justificación del umbral: retener cuesta un mes de interés a tasa `X` y rinde `Y − X` por mes;
se recupera en un mes exacto cuando `Y ≥ 2·X`. Retener del 14,64 % para atacar un 78,08 % ✔;
retener del 73,20 % para un 78,08 % ✘ (tardaría ~15 meses en pagarse).

Límites v1: mira solo M+1 (no M+2 en adelante); la proyección de M+1 usa su avalancha local
sin su propio look-ahead.

### 6.5 Balance del mes

`balance = capacity − consumo total del mes` (consumo = Σ `decidido − pagos_reales`, piso 0,
convertido). Pasa como `available` de M+1. Puede ser negativo (§6.2).

## 7. Arrastre (solo tarjetas)

Con los pagos decididos, el motor calcula `monthly_carry(monto efectivo, decidido, mínimo,
tasas)` por entry de tarjeta y **suma el resultado al monto efectivo de la entry de la misma
(tarjeta, moneda) del mes siguiente** — espejo de la cascada del timeline. El arrastre es de
simulación: no escribe `cash_flow_entries`.
El arrastre inicial (lo que viene de meses anteriores al mes actual) se calcula recorriendo
las series históricas de tarjeta con la regla de pago del timeline (planificado > real >
total asumido) y se suma a la primera entry simulada de cada (tarjeta, moneda).

El impago de deudas/gastos no se arrastra (el timeline tampoco lo hace hoy; provisional,
ver §10).

## 8. Materialización de pagos

Sin filas del plan, el timeline asume de cada egreso: *pago = pagos reales si > 0, si no el
total*. El motor crea una fila auto **solo cuando su decisión difiere de esa asunción**:

- `decidido == monto efectivo` y sin pagos reales → **sin fila** (el total ya se asume).
- `decidido == monto efectivo` con pagos reales parciales → **fila** (sin ella el timeline
  asumiría que el pago quedó en lo real y arrastraría).
- `decidido < monto efectivo` → **fila** que capea la entry en lo decidido — salvo que el
  manual ya sea exactamente la decisión (no se agrega nada).

La fila: `amount = decidido − manual` (en la **moneda de la entry**), `planned_date =
event_date` de la entry, `plan_id` del plan, `is_auto_generated = true`. Nunca se crean filas
con amount ≤ 0.

Resultado: en el timeline, `planned_amount` (manual + auto) refleja exactamente la decisión
del motor para cada egreso.

### 8.1 Ajuste al timeline (prerrequisito)

La cascada de arrastre del timeline hoy prioriza el pago real sobre el planificado
(`paid_real > 0 → payment = paid_real`). Con el Planning activo eso rompe la consistencia: si
el usuario pagó 6.000 de 18.196 y el motor planifica el total, el timeline arrastraría
intereses que el motor ya resolvió pagar.

Se invierte la prioridad en la cascada (`cash_flow_entry_service`, bloque de series de
tarjeta): **`payment = planificado si > 0, si no pago real si > 0, si no el monto`** (el
planificado es la intención total; el real es su ejecución parcial). El resto del timeline no
cambia.

## 9. Caso de referencia (datos reales, today = 2026-06-11)

Usuario `5309521d`, plan Estabilización `a07c64a7`, dial 42.000, `monthly_need` 27.000,
efectivo 38.500 $U + 126 USD (cotización 41).

**Junio:** capacity = 43.666 + 90.000 − 27.000 = 106.666.

- Paso 1 (obligatorios impagos): 13.800.
- Paso 2 (mínimos): 10.970,85 — deuda con tasas 1.300 entera; mínimos de tarjeta 5.802,
  10 USD, 290,78 y 77,27 USD (este último de un arrastre de mayo: entry cruda 0, efectiva
  515,15 USD, mínimo 15 %).
- Paso 3 (avalancha + look-ahead): paga enteras las tarjetas al 84,18 % (1.647,75), 78,08 %
  (55.670,29) y 73,20 % (12.196,23). Al llegar al 15,37 % (14c3 USD) y al 14,64 % (9e5f USD),
  el look-ahead detecta en julio demanda sin fondear a tasas > 2·X (≈ 25.992 al 73–78 %) y
  **reserva el resto (12.380,88)**: ambas tarjetas USD quedan al mínimo.
- Balance junio: 12.380,88. Filas auto: 3 — 18.196,23 (cap por real parcial de 6.000),
  10 USD y 77,27 USD (mínimos).

**Julio** (con un manual de 5.000 en la tarjeta e440 $U, que cubre su mínimo de 1.542,67):
el motor lo respeta como piso, paga la 9e5f $U entera otra vez (84,18 %), y el resto va
parcial a la 14c3 $U (78,08 %). Las tarjetas USD (con arrastre de junio) quedan al mínimo
recalculado al 15 %. El costo de respetar el manual queda visible en el arrastre (~+19 $U
contra la corrida sin manual).

Verificación transversal: en cada mes donde la plata alcanzó, consumo + reserva = capacity exacta
(diferencias solo por redondeo a centavos en parciales de moneda extranjera).

## 10. Limitaciones documentadas (provisional, evolucionará)

1. **Miopía más allá de M+1:** el look-ahead no ve M+2 en adelante. La solución completa es
   optimización multi-mes (descartada por YAGNI en v1); acá entrarán también los préstamos.
2. **Tasas nominales entre monedas:** un 78 % en pesos y un 15 % en USD no son comparables en
   términos reales si hay expectativa de devaluación. La app no proyecta tipo de cambio; se
   comparan nominales, consistente con el resto del modelo. Sesgo conocido: paga pesos primero
   y arrastra dólares.
3. **Arrastre solo de tarjetas:** una deuda con tasas dejada impaga no se arrastra al mes
   siguiente en el timeline ni en el motor (hoy es binaria: o entra en mínimos o cae en mora
   invisible). Iteración futura del timeline.
4. **El motor no re-corre solo:** si cambian los datos (compras, resúmenes, pagos), los pagos
   auto quedan desactualizados hasta la próxima corrida manual.

## 11. Errores

| Caso | Código | HTTP |
|---|---|---|
| Plan inexistente o ajeno | `not_found` | 404 |

(No hay más errores propios: sin settings cae al dial prorrateado, sin cotización cae a 1,
sin entries devuelve corrida vacía.)

## 12. Testing (TDD, nivel servicio)

Fixtures propias chicas (no los datos dev), `today` fijo inyectado. Casos:

1. Alcanza todo → paga todo, 0 filas auto (todo es "pago total asumido"), balance positivo.
2. Obligatorios y mínimos se pagan aunque el mes quede negativo (el rojo se ve en el timeline).
3. Avalancha: con sobrante limitado paga primero la tasa mayor; la última queda parcial.
4. Look-ahead: retiene cuando M+1 tiene demanda sin fondear a tasa > 2·X; NO retiene cuando
   la tasa futura no supera 2·X.
5. Respeta manuales: el manual es piso, consume capacidad, no genera fila si ya es la decisión.
6. Cap por real parcial: real 6.000 de 18.196 + decisión total → fila auto del total.
7. Arrastre: tarjeta al mínimo en M aumenta el monto efectivo de M+1 (mínimo recalculado 15 %).
8. Multi-moneda: compara y consume convertido, paga en moneda de la entry.
9. Re-corrida: borra solo los auto (los manuales sobreviven) y es idempotente.
10. Ajuste del timeline (§8.1): con planificado > real, la cascada usa el planificado.

## 13. Estructura de archivos

- `app/services/planning/__init__.py` — exporta `run_planning`.
- `app/services/planning/engine.py` — carga de datos + simulación + materialización.
- `app/routers/plans.py` — endpoint `POST /plans/{plan_id}/planning` (delega, devuelve 204).
- `app/services/cash_flow_entry_service.py` — ajuste §8.1 (prioridad planificado en cascada).
- `tests/test_planning.py` — casos §12.
