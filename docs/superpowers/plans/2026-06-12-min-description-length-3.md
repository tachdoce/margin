# Bajar mínimo de `description` a 3 — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bajar el mínimo de longitud de `description` de 8 a 3 caracteres para gastos, deudas, ingresos y financiaciones.

**Architecture:** Enfoque B (cambio mínimo): se cambia el número `8` por `3` en los tres lugares donde vive la regla (sin unificar). Cada uno de los tres paths de validación es independiente, así que cada Task lo cambia guiado por su propio test de borde positivo (descripción de exactamente 3 caracteres aceptada): falla con el mínimo actual de 8, pasa con 3.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest. Sin migraciones (es validación en servicio).

**Spec:** `docs/superpowers/specs/2026-06-12-min-description-length-3-design.md`

**Contexto base:**
- `cd backend && source .venv/bin/activate`; tests `pytest -q`.
- La regla lanza `AppError(ErrorCode.description_invalid, field="description")` en los tres lugares; todas las validaciones hacen `.strip()` antes de medir.
- Los tests de rechazo hoy usan `"corta"` (5 caracteres): con el mínimo nuevo de 3 pasarían a ser válidos, por eso se bajan a `"ab"` (2 caracteres) para que sigan probando el rechazo.

---

### Task 1: gastos y deudas (`obligation_common.py`)

`obligation_common.validate_description` es la función compartida que usan gastos y deudas. Cambiar su constante cubre ambas entidades.

**Files:**
- Modify: `app/services/obligation_common.py:6`
- Test: `tests/test_obligation_common.py`
- Test: `tests/test_expenses.py:101`

- [ ] **Step 1: Escribir el test de borde positivo**

En `tests/test_obligation_common.py`, después de `test_validate_description_trims` (línea ~46), agregar:
```python
def test_validate_description_minima_3():
    # 3 caracteres (tras strip) ahora es válido
    assert validate_description("UTE") == "UTE"
    assert validate_description("  abc  ") == "abc"
```

- [ ] **Step 2: Correr (falla)**

Run: `pytest tests/test_obligation_common.py::test_validate_description_minima_3 -q`
Expected: FAIL (con el mínimo actual de 8, `validate_description("UTE")` lanza `AppError`).

- [ ] **Step 3: Bajar la constante a 3**

En `app/services/obligation_common.py:6`, cambiar:
```python
MIN_DESCRIPTION_LENGTH = 8
```
por:
```python
MIN_DESCRIPTION_LENGTH = 3
```

- [ ] **Step 4: Correr (pasa)**

Run: `pytest tests/test_obligation_common.py::test_validate_description_minima_3 -q`
Expected: PASS.

- [ ] **Step 5: Actualizar los tests de rechazo (corta → ab)**

En `tests/test_obligation_common.py`, en `test_validate_description_corta`, cambiar:
```python
        validate_description("corta")
```
por:
```python
        validate_description("ab")
```

En `tests/test_expenses.py:101`, cambiar:
```python
    resp = client.post("/expenses", json=_recurrente(description="corta"), headers=headers)
```
por:
```python
    resp = client.post("/expenses", json=_recurrente(description="ab"), headers=headers)
```

- [ ] **Step 6: Correr los dos archivos de test (pasan)**

Run: `pytest tests/test_obligation_common.py tests/test_expenses.py -q`
Expected: PASS (borde positivo + rechazo actualizado + el resto sin regresión).

- [ ] **Step 7: Commit**

```bash
git add app/services/obligation_common.py tests/test_obligation_common.py tests/test_expenses.py
git commit -m "feat: mínimo de description 3 para gastos y deudas (obligation_common)"
```

---

### Task 2: ingresos (`income_service.py`)

Ingresos tiene su propia copia de la constante (no usa `obligation_common`). El borde positivo se prueba por HTTP creando un ingreso con descripción de 3 caracteres.

**Files:**
- Modify: `app/services/income_service.py:18`
- Test: `tests/test_incomes.py:124`

- [ ] **Step 1: Escribir el test de borde positivo**

En `tests/test_incomes.py`, después de `test_create_description_invalid` (línea ~126), agregar:
```python
def test_create_description_minima_3(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(description="UTE"), headers=_auth(client))
    assert resp.status_code == 201
```

- [ ] **Step 2: Correr (falla)**

Run: `pytest tests/test_incomes.py::test_create_description_minima_3 -q`
Expected: FAIL (422 `description_invalid` con el mínimo actual de 8, no 201).

- [ ] **Step 3: Bajar la constante a 3**

En `app/services/income_service.py:18`, cambiar:
```python
MIN_DESCRIPTION_LENGTH = 8
```
por:
```python
MIN_DESCRIPTION_LENGTH = 3
```

- [ ] **Step 4: Correr (pasa)**

Run: `pytest tests/test_incomes.py::test_create_description_minima_3 -q`
Expected: PASS.

- [ ] **Step 5: Actualizar el test de rechazo (corta → ab)**

En `tests/test_incomes.py:124`, cambiar:
```python
    resp = client.post("/incomes", json=_recurring_body(description="corta"), headers=_auth(client))
```
por:
```python
    resp = client.post("/incomes", json=_recurring_body(description="ab"), headers=_auth(client))
```

- [ ] **Step 6: Correr el archivo (pasa)**

Run: `pytest tests/test_incomes.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/income_service.py tests/test_incomes.py
git commit -m "feat: mínimo de description 3 para ingresos"
```

---

### Task 3: financiaciones (`financing_service.py`)

Financiaciones tiene el `8` hardcodeado inline dentro de `_validate_common`. Se baja a `3` (sigue inline, enfoque B). Borde positivo por HTTP.

**Files:**
- Modify: `app/services/financing_service.py:24`
- Test: `tests/test_financings_create.py:45`

- [ ] **Step 1: Escribir el test de borde positivo**

En `tests/test_financings_create.py`, después de `test_description_invalid` (línea ~46), agregar:
```python
def test_description_minima_3(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "description": "UTE"}
    r = client.post("/financings", json=body, headers=_headers(client))
    assert r.status_code == 201
```

- [ ] **Step 2: Correr (falla)**

Run: `pytest tests/test_financings_create.py::test_description_minima_3 -q`
Expected: FAIL (con el mínimo actual de 8 devuelve `description_invalid`, no 201).

- [ ] **Step 3: Bajar el literal a 3**

En `app/services/financing_service.py:24`, cambiar:
```python
    if description is None or len(description.strip()) < 8:
```
por:
```python
    if description is None or len(description.strip()) < 3:
```

- [ ] **Step 4: Correr (pasa)**

Run: `pytest tests/test_financings_create.py::test_description_minima_3 -q`
Expected: PASS.

- [ ] **Step 5: Actualizar el test de rechazo (corta → ab)**

En `tests/test_financings_create.py:45`, cambiar:
```python
    body = {**NO_SCHEDULE, "description": "corta"}
```
por:
```python
    body = {**NO_SCHEDULE, "description": "ab"}
```

- [ ] **Step 6: Correr el archivo (pasa)**

Run: `pytest tests/test_financings_create.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/financing_service.py tests/test_financings_create.py
git commit -m "feat: mínimo de description 3 para financiaciones"
```

---

### Task 4: Cierre

- [ ] **Step 1: Suite completa verde**

Run: `pytest -q`
Expected: PASS (toda la suite).

- [ ] **Step 2: Squash-merge a main**

```bash
git checkout main
git merge --squash feat/min-description-3
git commit -m "$(cat <<'EOF'
feat: mínimo de description baja de 8 a 3 (gastos, deudas, ingresos, financiaciones)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Borrar la rama (tras squash va -D)**

```bash
git branch -D feat/min-description-3
```

- [ ] **Step 4: Push**

```bash
git push
```

- [ ] **Step 5: Migraciones Alembic**

Esta feature **no agregó migraciones** (solo validación en servicio), así que no hay cadena que verificar. Confirmar igual que `alembic heads` sea un solo head antes de cerrar.
