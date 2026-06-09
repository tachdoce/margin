# credit_cards.due_day — Diseño

> Agregar a `credit_cards` un día de vencimiento (`due_day`), paralelo a `closing_day`, para que la **línea de
> tiempo use la fecha real de pago**: las proyecciones del `CashFlowEngine.credit_cards` fechan el egreso en el
> día de vencimiento en vez del día de cierre. El subdominio Tarjetas ya está completo; esto es una mejora
> acotada sobre él.

- **Fecha:** 2026-06-09
- **Estado:** aprobado para implementar
- **Depende de:** subdominio Tarjetas (tabla `credit_cards`, promote, `CashFlowEngine.credit_cards`, PATCH,
  `CreditCardOut`, web).
- **Cierre:** rama `feat/credit-cards-due-day`, **squash-merge** a `main`.
- **Nota:** se **recrea la base de dev** (drop + `alembic upgrade head`) para aplicar la columna NOT NULL sin
  backfill. Pierde los datos de prueba; hay que volver a registrar/cargar para probar.

---

## 1. Alcance

1. Columna `due_day` en `credit_cards`.
2. `promote` la precarga al crear la tarjeta.
3. `CashFlowEngine.credit_cards` R2 la usa para el `event_date` de las proyecciones (con heurística de mes).
4. `PATCH /credit-cards/{id}` la deja editar.
5. `CreditCardOut` la expone; la web la muestra y la edita.

**Fuera de alcance:** regla del reviewer para `due_day` (queda sin ciclo por ahora; los reviewers crecen).

---

## 2. Columna y migración

`due_day`: `smallint`, **NOT NULL**, sin `server_default` (la setea el backend, igual convención que
`closing_day`). Día del mes 1–31 del vencimiento de la tarjeta.

Migración: `op.add_column('credit_cards', sa.Column('due_day', sa.SmallInteger(), nullable=False))`. Como la
base de dev se recrea (tabla vacía), no hace falta backfill ni default. (Proyecto pre-producción; no hay datos
reales que migrar.)

Modelo `CreditCard`: agregar `due_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)` junto a
`closing_day`.

---

## 3. Promote — precarga

En `promote_staging_statement`, **solo en la rama de creación** de la tarjeta (tarjeta nueva):
`due_day = staging.due_date.day` (paralelo a `closing_day = staging.closing_date.day`). En la rama de
actualización (tarjeta existente/reactivada) **no se toca** (igual que `closing_day`). El `staging.due_date`
está garantizado no-NULL (la guarda de completitud de la madre exige los 10 obligatorios, incluido
`due_date`).

---

## 4. Motor — Responsabilidad 2 (proyecciones)

Hoy: `event_date = compute_event_date(year, month, card.closing_day, False)` para el mes proyectado.

Nuevo: el `event_date` se fecha en el **día de vencimiento**, en el mes correcto según la heurística:

```
# para cada mes de cierre proyectado (cy, cm):
if card.due_day >= card.closing_day:
    dy, dm = cy, cm            # vence el mismo mes que cierra
else:
    dy, dm = (cy, cm) + 1 mes  # vence el mes siguiente
event_date = compute_event_date(dy, dm, card.due_day, shift_weekends=False)
```

- `issue_year`/`issue_month` siguen siendo el **mes de cierre** (`cy`/`cm`) → la clave lógica
  `(source_type, source_id, issue_year, issue_month, currency_id)` **no cambia** (la reconciliación con R1 y
  con las reales sigue intacta).
- **R1 no cambia:** materializa el resumen real con `event_date = statement.due_date` (la fecha real).
- El cómputo del mes de vencimiento se hace con un helper local (`_add_months` ya existe en el motor para
  iterar; reusarlo).

> El `closing_day` se sigue usando para iterar los meses de cierre proyectados (M+1..horizonte) y como ancla;
> solo cambia el día/mes con que se calcula el `event_date`.

---

## 5. PATCH /credit-cards/{id}

Sumar `due_day` a `CreditCardUpdate` (opcional) y al servicio `update_credit_card`:
- Si vino `due_day`: validar 1 ≤ valor ≤ 31 → si no, 422 `due_day_invalid` (code ya existente, mensaje "El día
  de vencimiento debe estar entre 1 y 31.").
- Entra en el chequeo de `empty_patch` (el body debe traer al menos uno de los editables, ahora 4).
- Se actualiza como los demás; corre el reviewer + motor como hoy.

---

## 6. API + web

- `CreditCardOut`: agregar `due_day: int`.
- Web (`CreditCards.vue`): mostrar el `due_day` en la fila de la tarjeta (junto a "cierra {{closing_day}}") y
  agregarlo al form de edición inline (input number 1–31, junto a `closing_day`).

---

## 7. Tests

**Backend:**
- **Promote** (`tests/test_promote_credit_card_statements.py`): la tarjeta nueva queda con `due_day = día del
  due_date del staging`.
- **Motor** (`tests/test_cashflow_credit_cards.py`): proyección con `due_day >= closing_day` → `event_date` el
  mismo mes; con `due_day < closing_day` → mes siguiente. (Ajustar/extender los tests de R2 que hoy asumen
  `closing_day`.)
- **PATCH** (`tests/test_credit_cards_mutations.py`): editar `due_day` OK; fuera de 1–31 → 422
  `due_day_invalid`.
- **GET** (`tests/test_credit_cards_read.py`): `due_day` presente en la respuesta.
- Ajustar helpers/fixtures que crean `credit_cards` (p.ej. `_card_kwargs`) para incluir `due_day` (NOT NULL).

**Web:** verificación manual (banco de pruebas).

> Ojo con los tests existentes del motor R2: hoy esperan `event_date` con el `closing_day`. Hay que
> actualizarlos al `due_day` (los helpers de tarjeta deben setear un `due_day` conocido).

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/credit-cards-due-day`), TDD:
1. Modelo `due_day` + migración; recrear DB de dev.
2. Promote (precarga al crear) + tests.
3. Motor R2 (heurística de mes) + tests (actualizar los existentes).
4. PATCH (`due_day` + validación) + tests.
5. `CreditCardOut` + web.
6. Suite completa verde → cierre.
