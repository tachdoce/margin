# bcrypt cost configurable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el cost factor de bcrypt sea configuración (`Settings.bcrypt_rounds`, default 12) en vez de un literal hardcodeado, para que el entorno de test use cost 4 y la suite pase de ~2:11 a ~0:35.

**Architecture:** Una sola fuente de verdad: `Settings.bcrypt_rounds`. `security.py` arma `pwd_context` con ese valor. `conftest.py` setea `BCRYPT_ROUNDS=4` **antes** de importar la app (porque `pwd_context` y `settings` se construyen al importar). Prod/dev sin env var → 12, idéntico a hoy.

**Tech Stack:** FastAPI, pydantic-settings, passlib[bcrypt], pytest. Rama `feat/bcrypt-rounds-config` (salida de `main`).

**Spec:** `docs/superpowers/specs/2026-06-16-bcrypt-rounds-config-design.md`

**Convención de commits:** cada commit termina con la línea
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- **Crear** `backend/tests/test_security_rounds.py` — test: `hash_password` embebe `settings.bcrypt_rounds`.
- **Modificar** `backend/app/core/config.py` — agregar `bcrypt_rounds: int = 12` a `Settings`.
- **Modificar** `backend/app/core/security.py` — `pwd_context` usa `settings.bcrypt_rounds`.
- **Modificar** `backend/tests/conftest.py` — setear `BCRYPT_ROUNDS=4` al tope, antes de los imports de la app.

---

## Task 1: bcrypt cost configurable + entorno de test en cost 4

**Files:**
- Create: `backend/tests/test_security_rounds.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/security.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Write the failing test**

Crear `backend/tests/test_security_rounds.py`:

```python
from app.core.config import settings
from app.core.security import hash_password


def test_hash_uses_configured_rounds():
    """El hash bcrypt embebe el cost como 3er segmento $: $2b$<NN>$...

    Verifica el mecanismo (el cost sale de settings), no mide tiempos.
    En entorno de test settings.bcrypt_rounds == 4, así que el segmento es "04".
    """
    h = hash_password("12345678")
    cost_segment = h.split("$")[2]
    assert cost_segment == f"{settings.bcrypt_rounds:02d}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_security_rounds.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'bcrypt_rounds'` (el campo todavía no existe).

- [ ] **Step 3: Add `bcrypt_rounds` to Settings**

En `backend/app/core/config.py`, dentro de la clase `Settings`, agregar el campo después de `secret_key` (línea 14):

```python
    bcrypt_rounds: int = 12
```

(Queda: `secret_key`, `bcrypt_rounds`, `jwt_expire_days`, ...)

- [ ] **Step 4: Use the setting in `security.py`**

En `backend/app/core/security.py`, reemplazar la línea 10:

```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
```

por:

```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.bcrypt_rounds)
```

(`settings` ya está importado en la línea 7.)

- [ ] **Step 5: Set cost 4 for the test environment**

En `backend/tests/conftest.py`, agregar **al tope del archivo, antes de la línea 1** (`import pytest`):

```python
import os

os.environ.setdefault("BCRYPT_ROUNDS", "4")  # acelera la suite; prod/dev quedan en 12
```

> **Por qué antes de todo:** la línea 6 (`from app.core.config import settings`) construye
> `settings` leyendo el entorno una sola vez, y la 10 de `security.py` arma `pwd_context` con ese
> valor. Si la env var no está seteada antes de esos imports, el cost queda en 12. `setdefault`
> permite override manual (correr la suite en cost 12 exportando `BCRYPT_ROUNDS=12`) sin pisarlo.

- [ ] **Step 6: Run the new test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_security_rounds.py -q`
Expected: PASS. (`settings.bcrypt_rounds == 4` en test → el hash empieza con `$2b$04$`.)

- [ ] **Step 7: Run the full suite — verde y rápida**

Run: `cd backend && .venv/bin/pytest -q --durations=5`
Expected: toda la suite verde, en **~35s** (vs ~2:11 antes). En `--durations=5` los tests de auth
(`test_login_ok`, `*_other_user_404`, `test_hash_and_verify_password`) ya no aparecen arriba: bajan
de ~0,5–0,7s a milisegundos.

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/config.py backend/app/core/security.py backend/tests/conftest.py backend/tests/test_security_rounds.py
git commit -m "$(cat <<'EOF'
feat(security): bcrypt cost configurable; test usa cost 4

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Cierre — squash-merge a main

**Files:** ninguno (operación de git).

> No hay migración en este feature, así que **no aplica** el chequeo de linealidad de Alembic.

- [ ] **Step 1: Suite completa verde una última vez**

Run: `cd backend && .venv/bin/pytest -q`
Expected: toda la suite verde (en ~35s).

- [ ] **Step 2: Squash-merge a `main`**

```bash
git checkout main
git merge --squash feat/bcrypt-rounds-config
git commit -m "$(cat <<'EOF'
feat(security): bcrypt cost configurable (test usa cost 4, prod 12)

Suite de tests pasa de ~2:11 a ~0:35. Spec y plan en docs/superpowers/.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Borrar la rama de feature**

```bash
git branch -D feat/bcrypt-rounds-config
```

- [ ] **Step 4: Push de `main`** (solo si el usuario lo pide; en trabajo autónomo, no pushear)

```bash
git push origin main
```

---

## Cierre

Con bcrypt en `main`, para llevar la mejora a `spike/space`:

```bash
git checkout spike/space
git merge main
```

Los tests del spike también corren rápido a partir de ahí.
