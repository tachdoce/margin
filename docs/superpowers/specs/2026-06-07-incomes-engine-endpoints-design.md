# Slice 3 — Endpoints de ingresos con el motor + borrado híbrido — Diseño

> Tercer y último slice de conectar **Ingresos** con la **línea de tiempo del flujo de caja**. Cablea los
> endpoints de ingresos para que ejecuten `CashFlowEngine.incomes` en su transacción, y reemplaza el
> borrado provisorio (soft incondicional) por el **híbrido hard/soft** que define Notion. El *qué* vive en
> Notion → Endpoints → Ingresos (POST/PATCH/DELETE/reactivate) y Backend → Engines → CashFlowEngine → incomes.

- **Fecha:** 2026-06-07
- **Estado:** aprobado para implementar
- **Depende de:** `incomes` (endpoints ya existen), `CashFlowEngine.incomes` (slice 2, en `main`),
  `cash_flow_entries`/`cash_flow_payments` (slice 1, en `main`).
- **Cierre:** rama `feat/incomes-engine-endpoints`, **squash-merge** a `main`.

---

## 1. Alcance

Todo el cambio es **interno a `app/services/income_service.py`**. El contrato de los endpoints **no cambia**:
mismos status codes, mismos schemas (`IncomeOut`/`IncomeListOut`), mismo router. No se agregan error codes.

- **Cablear el motor** en `create_income`, `update_income`, `reactivate_income`: corren
  `materialize_income(db, income.id)` en la misma transacción, antes del commit.
- **Reescribir `delete_income`**: del soft incondicional provisorio al híbrido hard/soft.

**Fuera de alcance:** los demás motores de la familia (`expenses`, `debts`, etc.), los endpoints de
`cash_flow_*` (timeline, payments, by-source), y cualquier cambio al router o a los schemas de ingresos.

---

## 2. Cableado del motor (create / update / reactivate)

Hoy las tres funciones hacen `db.commit()` directo tras modificar el income. Pasan a:

```
... crea/actualiza la fila del income (igual que hoy) ...
db.flush()                          # la fila existe/está actualizada para el SELECT ... FOR UPDATE del motor
materialize_income(db, income.id)   # (re)genera las cash_flow_entries en la misma transacción
db.commit()
db.refresh(income)
return income
```

- **`create_income`**: tras `db.add(income)` → `db.flush()` → `materialize_income` → commit → refresh.
- **`update_income`**: tras aplicar los cambios al income → `db.flush()` → `materialize_income` → commit →
  refresh. (Sigue filtrando `deleted_at IS NULL` al buscar, como hoy.)
- **`reactivate_income`**: tras `income.deleted_at = None` → `db.flush()` → `materialize_income` → commit →
  refresh. El motor relee el income ya vigente y regenera sus entries futuras.

Si `materialize_income` lanza excepción, la transacción no commitea (rollback total): nunca queda un income
sin sus entries ni entries a medias. El motor controla su propio lock (`FOR UPDATE`); el servicio sigue
siendo el único punto de commit/rollback de la operación.

`import`: agregar `from app.services.cash_flow.incomes import materialize_income` en `income_service.py`.

---

## 3. Borrado híbrido (`delete_income`)

Reemplaza la implementación provisoria (que seteaba `deleted_at` siempre). Todo en una transacción. **No**
invoca al motor — el endpoint orquesta el borrado con SQL directo (Notion: el borrado no pasa por
materialización).

1. Buscar el income con `id`, `user_id` del token y `deleted_at IS NULL`. Si no existe → `AppError(not_found)`
   (404). (Igual que hoy; cubre "no existe / no es del usuario / ya soft-deleted".)
2. Contar los pagos **reales** (`plan_id IS NULL`) imputados a las `cash_flow_entries` del income:
   ```sql
   SELECT COUNT(*) FROM cash_flow_payments cp
   JOIN cash_flow_entries cfe ON cp.cash_flow_entry_id = cfe.id
   WHERE cfe.source_type = 'ingreso' AND cfe.source_id = <income.id>
     AND cp.plan_id IS NULL;
   ```
3. **Caso A — count = 0 → hard-delete total:**
   - Borrar todas las `cash_flow_entries` del income (`source_type='ingreso'` AND `source_id=income.id`); sus
     `cash_flow_payments` planificados caen por `ON DELETE CASCADE`.
   - Borrar la fila de `incomes`.
4. **Caso B — count > 0 → soft-delete:**
   - Borrar las `cash_flow_entries` del income que **no** tienen pago real (subquery **acotado a las entries
     de este income**, refinamiento sobre el SQL global de Notion). Sus planificados caen por cascade.
   - Setear `income.deleted_at = now()`.
   - Las entries con pago real **sobreviven** apuntando al income soft-deleted (preservan la historia).
5. `db.commit()`. Response **204** en ambos casos (la distinción es transparente al cliente).

Consecuencia (correcta, definida en Notion): un income hard-deleted ya no existe → `POST /incomes/{id}/reactivate`
posterior responde 404. Un soft-deleted se reactiva y re-materializa (sección 2).

---

## 4. Decisiones, con su porqué

- **El cambio vive en el servicio, no en el router:** el router ya es finito y delega; la materialización y
  el borrado son lógica de negocio. El contrato HTTP no se toca.
- **`flush` antes de materializar:** el motor relee el income con `FOR UPDATE`; la fila tiene que estar en la
  base (flushada) dentro de la transacción. En `create` la fila es nueva pero ya flushada; el lock sobre la
  propia fila no commiteada es válido.
- **El borrado lo decide el endpoint, no el motor:** el motor es un traductor sync sin canal con el usuario;
  permitir el borrado y elegir hard/soft es responsabilidad del endpoint (Notion).
- **Subquery del soft-delete acotado al income:** correctitud y eficiencia; evita escanear todos los pagos
  reales del sistema (el SQL de Notion usaba un subquery global, equivalente pero más amplio).
- **204 estable en ambos casos:** el cliente no necesita saber si fue hard o soft; mantiene el contrato si en
  el futuro cambia la heurística.

---

## 5. Tests

Se agregan/actualizan en `tests/test_incomes.py` (o un archivo dedicado si queda más limpio). Los casos de
delete/reactivate existentes **cambian de semántica** y se actualizan.

- **create materializa:** tras `POST /incomes` (recurrente), las `cash_flow_entries` del income existen
  (consultando la tabla con un `today` controlado, o verificando el count esperado).
- **PATCH `amount` re-materializa:** editar el monto actualiza las entries (mismo count, nuevo `amount`).
- **reactivate re-materializa:** un income soft-deleted, al reactivarse, vuelve a tener entries futuras.
- **delete sin pagos reales → hard:** tras `DELETE`, no quedan `cash_flow_entries` del income y la fila de
  `incomes` no existe; un `reactivate` posterior da 404.
- **delete con pago real → soft:** sembrando una entry con un `cash_flow_payments` real, el `DELETE` conserva
  esa entry, borra las demás, y el income queda con `deleted_at` (aparece en `GET` con `is_deleted=true`); el
  `reactivate` lo revive.
- **regresión:** los tests de validación de POST/PATCH (modelo binario, error codes) siguen verdes; `pytest -q`
  verde.

**Nota de testabilidad:** como la materialización depende de "hoy", los tests que verifican entries pueden
necesitar controlar la fecha. Dos opciones a resolver en el plan: (a) verificar solo el *count*/existencia con
un income cuyo cronograma caiga seguro en el futuro respecto de `date.today()`, o (b) si hiciera falta fijar
`today`, exponerlo. Se prefiere (a) — no cambiar la firma del servicio por los tests; el servicio llama a
`materialize_income(db, income.id)` con el `today` real, y los tests usan un income con fechas holgadas.

---

## 6. Cierre de la tanda

Con este slice, crear/editar/reactivar un ingreso materializa su línea de tiempo, y borrarlo aplica el
híbrido hard/soft real. Cierra la conexión Ingresos → flujo de caja. Quedan, para más adelante, los otros
motores de la familia y los endpoints de consulta de `cash_flow_*`.
