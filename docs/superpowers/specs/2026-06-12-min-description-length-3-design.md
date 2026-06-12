# Bajar mínimo de longitud de `description` a 3 — Diseño

## Objetivo

Bajar el mínimo de longitud de `description` de **8 a 3** caracteres para **gastos, deudas, ingresos y financiaciones**. Hoy el mínimo de 8 rechaza descripciones legítimas y cortas ("UTE", "Antel", "Sueldo").

## Alcance

- **Incluye:** gastos, deudas, ingresos, financiaciones.
- **No incluye:** planes (`name` solo exige no-vacío, sin mínimo de longitud) ni plan_movements (`description` opcional, sin regla). No se tocan.
- **Enfoque elegido: B (cambio mínimo).** Se cambia el número `8` por `3` en los tres lugares donde vive, sin refactor ni unificación. Se descartó unificar las tres copias en una sola constante (enfoque A) para minimizar superficie de cambio.

## Estado actual

La regla "description ≥ 8" vive duplicada en tres lugares, todos lanzando el mismo `ErrorCode.description_invalid`:

| Archivo | Forma actual | Entidades que cubre |
|---|---|---|
| `app/services/obligation_common.py:6` | `MIN_DESCRIPTION_LENGTH = 8` (constante, usada por `validate_description`) | gastos, deudas |
| `app/services/income_service.py:18` | `MIN_DESCRIPTION_LENGTH = 8` (copia propia, usada por `_validate_description`) | ingresos |
| `app/services/financing_service.py:24` | `len(description.strip()) < 8` (literal inline, dentro de `_validate_common`) | financiaciones |

Las tres validaciones hacen `.strip()` antes de medir (los espacios no cuentan) y lanzan `AppError(ErrorCode.description_invalid, field="description")`.

## Cambios

Tres ediciones de una línea cada una, sin tocar estructura, funciones ni el `ErrorCode`:

1. `obligation_common.py:6` — `MIN_DESCRIPTION_LENGTH = 8` → `MIN_DESCRIPTION_LENGTH = 3`. Cubre **gastos** y **deudas** automáticamente.
2. `income_service.py:18` — `MIN_DESCRIPTION_LENGTH = 8` → `MIN_DESCRIPTION_LENGTH = 3`. Cubre **ingresos**.
3. `financing_service.py:24` — `< 8` → `< 3`. Cubre **financiaciones** (sigue hardcodeado, enfoque B).

Comportamiento resultante uniforme: descripción con < 3 caracteres (tras `strip`) → `description_invalid`; ≥ 3 → válida.

## Testing

Los tests de rechazo por descripción corta hoy usan `"corta"` (5 caracteres), que con el nuevo mínimo de 3 pasaría a ser **válida**. Hay que bajar el string a uno de < 3 caracteres (ej. `"ab"`) para que sigan probando el rechazo:

- `tests/test_obligation_common.py:50` — `validate_description("corta")` → `validate_description("ab")`
- `tests/test_expenses.py:101` — `description="corta"` → `description="ab"`
- `tests/test_incomes.py:124` — `description="corta"` → `description="ab"`
- `tests/test_financings_create.py:45` — `"description": "corta"` → `"description": "ab"`

Además, para fijar el nuevo borde inferior, agregar en cada uno (o al menos en el unit test compartido `test_obligation_common.py`) una aserción de que una descripción de **exactamente 3 caracteres** ahora se acepta (antes era rechazada). Esto documenta el cambio de regla y previene regresiones.

Los tests de camino feliz existentes usan descripciones ≥ 8 ("Alquiler depto", "Préstamo personal banco", etc.), que siguen siendo válidas — no requieren cambios.

## Riesgos

Mínimos. No hay migración (es validación en servicio, no schema de DB). No hay impacto en datos existentes. La única asimetría que persiste —`description` de plan_movements sigue sin regla— es preexistente y queda fuera de alcance por decisión explícita.
