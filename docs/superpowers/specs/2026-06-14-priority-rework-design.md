# Rework del concepto de prioridad — Diseño (modelo de datos)

> **Alcance:** esta spec cubre **solo el modelo de datos** y la **eliminación del sistema viejo**
> (`priority_levels`). El **algoritmo del planning** que consume estos campos se diseña aparte
> (diferido por decisión del usuario).

## Objetivo

Reemplazar el catálogo fijo `priority_levels` por campos de prioridad y regla de pago, por deuda,
controlados por el usuario. El usuario decide qué pagar de cada deuda y en qué orden.

## Contexto / por qué se cambia

- Hoy `priority_levels` es un catálogo fijo de 6 niveles (Ineludible, Esencial, Obligación crítica,
  Obligación prioritaria, Obligación manejable, Ajustable) que **mezcla varios conceptos en una sola
  escala**: esencialidad, consecuencia de no pagar, velocidad a la que crece (tasa), flexibilidad, y
  quién lo asigna (el "Ineludible" lo pone el sistema).
- **No lo usa el motor**: ni `app/services/planning/engine.py` ni el timeline (`cash_flow_entry_service`)
  miran la prioridad. Solo se valida y se guarda (`obligation_common`, `debt_service`, `expense_service`)
  y se expone en `bootstrap`. Por eso reemplazarlo es de **bajo riesgo funcional**.

## Decisión

Eliminar `priority_levels` y modelar la prioridad como campos por deuda.

### Campos nuevos

| columna | tipo | qué guarda |
|---|---|---|
| `priority` | int, nullable | orden para ejecutar la acción obligada. Solo tiene valor cuando `payment_rule` ≠ `ninguno`. |
| `payment_rule` | enum (`ninguno`/`minimo`/`total`/`mensual`) | qué hay que pagar de esa deuda. Default `ninguno`. |
| `monthly_paydown_amount` | numeric(12,2), nullable | monto mínimo a saldar por mes. Solo cuando `payment_rule = mensual`. |
| `priority_open_debt` | int, nullable | orden entre deudas abiertas para asignar el excedente. |

### Dónde vive cada campo

- `priority`, `payment_rule` → `obligations` con `obligation_kind = deuda`, y `credit_cards`.
- `payment_rule = mensual` + `monthly_paydown_amount` + `priority_open_debt` → `obligations` con
  `obligation_kind = deuda_abierta` (lo que el usuario llama "deuda informal": le debés a alguien,
  sin cronograma fijo).

> Nota de terminología: "deuda informal" en el código es la obligación de tipo `deuda_abierta`.

> **`plan_movements` no lleva estas columnas.** El planning los trata como `priority` NULL
> (sin acción obligada). Los campos viven solo en deudas reales: `obligations` + `credit_cards`.

### Valores permitidos de `payment_rule` por tipo

- `ninguno`: todos (es el **default**).
- `minimo`: solo deuda y tarjeta.
- `total`: solo deuda y tarjeta.
- `mensual`: solo deuda informal (`deuda_abierta`).

### Semántica (reglas duras para el planning)

- `ninguno`: sin obligación especial; se paga si entra en el orden / si sobra.
- `minimo`: el planning debe pagar **el mínimo** de esa deuda sí o sí.
- `total`: el planning debe **saldarla completa** sí o sí.
- `mensual`: el planning debe poner **al menos `monthly_paydown_amount` por mes** en esa deuda informal.
  Ejemplo: debo 100.000, pero quiero pagar ≥ 2.000 cada mes.
- `priority`: cuando hay acciones obligadas, define **el orden** en que se ejecutan.
- `priority_open_debt`: cuando sobra plata, define **el orden de saldado** entre deudas abiertas.

### Convenciones

- Nombre de columna en inglés snake_case; **valores del enum en español** (regla del repo).
- Montos `numeric(12,2)` + `Decimal`.

## Eliminación de `priority_levels`

Se borra por completo, con sus FKs:

- **Tabla**: `priority_levels`.
- **FKs / columnas que la referencian**:
  - `obligations.priority_level` (FK → `priority_levels.level`).
  - `obligation_types.default_priority_level` (FK → `priority_levels.level`).
- **Modelo**: quitar `app/models/priority_level.py` y su registro en `app/models/__init__.py`.
- **Servicios**: quitar `validate_priority` y `SYSTEM_PRIORITY_LEVEL` de `obligation_common.py`; quitar el
  uso de prioridad en `debt_service.py` y `expense_service.py`; sacar el catálogo `priority_levels` de
  `bootstrap_service.py`.
- **Schemas**: sacar `priority_level` de `debt.py` y `expense.py`; sacar `priority_levels` de `bootstrap.py`.
- **Concepto "adelanto de sueldo / Ineludible"**: se elimina por completo. Borrar el `obligation_type`
  `adelanto_sueldo` (id 6) y cualquier rastro del nivel asignado por el sistema (`SYSTEM_PRIORITY_LEVEL`).
- **Endpoints**: `debts` y `expenses` (create/update) dejan de pedir/aceptar `priority_level` y pasan a
  aceptar los campos nuevos según corresponda; `credit_cards` (update) acepta `priority`/`payment_rule`.
- **Migración Alembic**: drop de los FKs + columnas + tabla + el tipo `adelanto_sueldo`; alta de las
  columnas nuevas + el tipo enum.

## Fuera de alcance (diferido)

- El **algoritmo del planning** que consume estos campos: cómo reparte la plata entre los `minimo`,
  los `total`, el `mensual` y el excedente, y cómo usa `priority` y `priority_open_debt`. Se diseña en
  una spec aparte, más adelante.

## Decisiones resueltas

1. **`plan_movements`**: no lleva estos campos; el planning los trata como `priority` NULL. Los campos
   viven solo en `obligations` (`deuda`, `deuda_abierta`) y `credit_cards`.
2. **"Ineludible / adelanto de sueldo"**: se descarta el concepto (incluido el `obligation_type`
   `adelanto_sueldo` y el nivel de sistema).
3. **`obligation_types`**: no se le agregan defaults; cada endpoint maneja los suyos. No cambia más allá
   de que pierde el FK `default_priority_level` (parte de la remoción de `priority_levels`).
4. **`priority` y `priority_open_debt` quedan separados** (decisión del usuario).

Queda una sola suposición: **datos existentes** — se asume base de dev limpia (drop directo); si hay
datos a preservar, ajustar la migración antes de correrla.

## Testing (cuando se implemente)

- Crear deuda/gasto ya no requiere ni acepta `priority_level`.
- Validación: `payment_rule` permitido según el tipo; `monthly_paydown_amount` solo válido con `mensual`.
- `bootstrap` ya no expone `priority_levels`.
