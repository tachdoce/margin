# Scoping por país (módulo compartido) — Diseño

> Un módulo transversal que centraliza la regla recurrente **"una entidad referenciada tiene que
> pertenecer al país del usuario"**. Hoy se aplica a `currency`; mañana a `institutions` y otras
> referencias scopeadas por país. Elimina la duplicación actual (`_validate_currency` copiado idéntico en
> dos servicios) y deja el riel puesto antes de arrancar **Obligaciones**, que valida `currency_id` en
> `POST /expenses` y `POST /debts`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Tipo:** refactor (preserva comportamiento) + base para features futuras.
- **Depende de:** `currencies`, `users` (ya existentes). No toca BD ni endpoints.
- **Cierre:** rama `feat/scoping-por-pais`, **squash-merge** a `main`.

---

## 1. Problema

La regla "el `currency_id` que mandó el usuario tiene que ser de su país" está implementada **tres veces**:

- `income_service._validate_currency` ([income_service.py:27-30](../../../backend/app/services/income_service.py#L27-L30))
- `plan_movement_service._validate_currency` ([plan_movement_service.py:41-44](../../../backend/app/services/plan_movement_service.py#L41-L44)) — **copia byte a byte** de la anterior.
- (Variante *derivar*, no *validar*) `plan_service._legal_tender_currency` ([plan_service.py:21-27](../../../backend/app/services/plan_service.py#L21-L27)).

Las dos primeras son duplicación literal: el día que la regla cambie (multi-moneda, soft-delete de
referencias, etc.) hay que tocar dos lugares y es fácil desincronizarlos. Y se vienen más consumidores:
Obligaciones valida `currency_id`, e `institutions` (futuro) replicará el mismo patrón con otro modelo.

## 2. Enfoque: primitiva genérica + wrappers tipados

Dos capas, en un módulo nuevo `app/services/scoping.py`:

### Capa 1 — la regla, en un solo lugar

```python
from typing import TypeVar
from sqlalchemy.orm import Session
from app.core.errors import AppError, ErrorCode
from app.models.user import User

T = TypeVar("T")

def require_country_scoped(
    db: Session,
    user: User,
    model: type[T],
    entity_id,
    *,
    error: ErrorCode,
    field: str,
) -> T:
    """Devuelve la entidad `model` con `entity_id` si pertenece al país del usuario.
    Lanza AppError(error, field=field) si no existe o es de otro país.
    Convención: `model` debe exponer la columna `country_code`."""
    entity = db.get(model, entity_id) if entity_id is not None else None
    if entity is None or entity.country_code != user.country_code:
        raise AppError(error, field=field)
    return entity
```

Esta función **es** la única definición de "pertenece a mi país". `entity_id is None` → se trata como no
encontrada (lanza). Devuelve la entidad (los callers que solo validan ignoran el retorno).

### Capa 2 — un wrapper por modelo (le da nombre y su error code/field)

```python
from app.models.currency import Currency

def require_user_currency(db: Session, user: User, currency_id: int | None) -> Currency:
    return require_country_scoped(
        db, user, Currency, currency_id,
        error=ErrorCode.currency_not_available, field="currency_id",
    )
```

Agregar un modelo nuevo (ej. `institutions`) = un wrapper de 3 líneas + su error code. **No** se
reimplementa la regla. *(El wrapper de institutions NO entra en este slice — YAGNI: se agrega cuando exista
la tabla.)*

### La variante *derivar* (no validar), co-localizada

`legal_tender_currency` se **mueve** desde `plan_service` al mismo módulo, porque es el mismo concepto
(scoping por país de la moneda) en su forma "derivar del país" en vez de "validar lo que vino del body".
No comparte firma con `require_country_scoped` (no recibe id), pero vivir juntas hace del módulo el hogar
único de la regla. Se renombra de `_legal_tender_currency` (privado) a `legal_tender_currency` (público del
módulo).

```python
from sqlalchemy import select

def legal_tender_currency(db: Session, user: User) -> Currency:
    """Moneda de curso legal del país del usuario (se deriva, no viene del body)."""
    return db.execute(
        select(Currency).where(
            Currency.country_code == user.country_code,
            Currency.is_legal_tender.is_(True),
        )
    ).scalars().first()
```

## 3. Migración de los call sites (preserva comportamiento)

- **`income_service`**: borrar `_validate_currency`; `from app.services.scoping import require_user_currency`;
  reemplazar las 2 llamadas ([:73](../../../backend/app/services/income_service.py#L73),
  [:123](../../../backend/app/services/income_service.py#L123)) por `require_user_currency(db, user, payload.currency_id)`.
  Quitar el import de `Currency` si queda sin uso.
- **`plan_movement_service`**: ídem; reemplazar [:78](../../../backend/app/services/plan_movement_service.py#L78)
  y [:142](../../../backend/app/services/plan_movement_service.py#L142). Quitar `Currency` si queda sin uso.
- **`plan_service`**: borrar `_legal_tender_currency`;
  `from app.services.scoping import legal_tender_currency`; reemplazar los 3 usos
  ([:43](../../../backend/app/services/plan_service.py#L43), [:68](../../../backend/app/services/plan_service.py#L68),
  [:128](../../../backend/app/services/plan_service.py#L128)). Quitar `Currency`/`select` si quedan sin uso.

El comportamiento observable no cambia: mismos error codes (`currency_not_available`, field `currency_id`),
mismo resultado de la query de curso legal. La suite existente (incomes, plan_movements, plans) es la red de
seguridad.

## 4. Tests

- **Red de seguridad:** la suite completa (`pytest -q`) debe seguir verde sin tocar tests existentes — es lo
  que garantiza que el refactor no cambió comportamiento.
- **Test unitario nuevo** `tests/test_scoping.py` para fijar el contrato del módulo en sí:
  - `require_country_scoped` devuelve la entidad cuando es del país del usuario.
  - lanza `AppError` con el `error`/`field` dados cuando `entity_id` es de otro país.
  - lanza cuando `entity_id` es `None`.
  - lanza cuando `entity_id` no existe.
  - `require_user_currency` devuelve la `Currency` del país y lanza `currency_not_available`/`currency_id`
    para una moneda de otro país.
  - `legal_tender_currency` devuelve la moneda de curso legal del país del usuario.
  - (Usa fixtures `db_session` + `seed_uy` + `seed_uy_currency`; siembra una currency de otro país para los
    casos negativos.)

## 5. Decisiones, con su porqué

- **`scoping.py` (nombre neutro), no `currency_rules.py`:** el patrón es "scoping por país", no algo de
  moneda; el nombre sobrevive a la llegada de `institutions` y demás.
- **Genérica + wrapper, no solo wrappers ni solo genérica:** la genérica centraliza la regla (consistencia
  garantizada); los wrappers mantienen los call sites legibles y cada modelo conserva su error code/field
  propio, que es la única parte específica del modelo.
- **Convención que asienta:** toda tabla de referencia scopeada por país expone `country_code`. Cuando una
  entidad scopee distinto (vía join, `is_legal_tender`, etc.), se escribe una función dedicada — la
  excepción consciente, no la regla. (Se documenta en `backend/CLAUDE.md`.)
- **Co-localizar `legal_tender_currency`:** mismo concepto de dominio; el módulo queda como hogar único de
  scoping por país de la moneda (validar + derivar).
- **Sin RLS de Postgres / capa de repositorios / clase base de servicio:** over-engineering para el tamaño
  actual (YAGNI).

## 6. Fuera de alcance

- El subdominio **Obligaciones** (tablas, ReviewEngine, CashFlowEngine.expenses/debts/open_debts, endpoints)
  — slice siguiente; este solo deja el riel de scoping.
- El wrapper `require_user_institution` — se agrega cuando exista la tabla `institutions`.
- Cualquier cambio de comportamiento en incomes/plan_movements/plans.

## 7. Plan de implementación (orientativo)

Un slice (`feat/scoping-por-pais`), TDD:
1. `tests/test_scoping.py` (rojo) → `app/services/scoping.py` con `require_country_scoped` +
   `require_user_currency` + `legal_tender_currency` (verde) → commit.
2. Migrar los 3 servicios a importar del módulo; correr la suite completa (verde, sin tocar tests
   existentes) → commit.
3. Documentar la convención `country_code` en `backend/CLAUDE.md` → commit.
