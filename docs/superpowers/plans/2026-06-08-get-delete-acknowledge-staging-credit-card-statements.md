# GET / DELETE / acknowledge staging-credit-card-statements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Agregar los tres endpoints chicos del staging: `GET /credit-card-statements`,
`DELETE /credit-card-statements`, `POST /credit-card-statements/acknowledge`.

**Architecture:** Crecen el router/servicio del recurso. GET solo lectura (reusa `StagingStatementOut`);
DELETE hard-delete (cascade); acknowledge UPDATE puntual preservando `updated_at` (Core `update().values`,
patrón `acknowledge_obligation`). Un error code nuevo. Sin schemas nuevos.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (TestClient).

**Spec:** `docs/superpowers/specs/2026-06-08-get-delete-acknowledge-staging-credit-card-statements-design.md`

**Branch:** `feat/staging-credit-card-statements-chicos` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/staging-credit-card-statements-chicos
```

---

## Task 1: Error code nuevo

**Files:**
- Modify: `app/core/errors.py`

- [ ] **Step 1: Agregar** después de `item_incomplete = (...)`:

```python
    statement_has_no_findings = (409, "El resumen no tiene observaciones para reconocer.")
```

---

## Task 2: Servicio + router + tests (TDD)

**Files:**
- Modify: `app/services/credit_card_statement_service.py`
- Modify: `app/routers/credit_card_statements.py`
- Modify: `tests/test_credit_card_statements.py`

- [ ] **Step 1: Agregar los tests (rojo)** — al final de `tests/test_credit_card_statements.py`:

```python
# ---- GET ----

def test_get_200(client, cc_catalog):
    headers = _auth(client)
    posted = _post_staging(client, headers)
    r = client.get("/credit-card-statements", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == posted["id"]
    assert len(body["items"]) == len(posted["items"])
    assert all("missing_fields" in it for it in body["items"])


def test_get_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    assert client.get("/credit-card-statements", headers=headers).status_code == 404


def test_get_reflects_puts(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    client.put("/credit-card-statements", json=_madre_body(current_limit=999999.00), headers=headers)
    body = client.get("/credit-card-statements", headers=headers).json()
    assert body["current_limit"] == "999999.00"


def test_get_does_not_rereview(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    first = client.get("/credit-card-statements", headers=headers).json()
    second = client.get("/credit-card-statements", headers=headers).json()
    assert first["review_findings"] == second["review_findings"]
    assert first["is_ready"] == second["is_ready"]


# ---- DELETE ----

def test_delete_204(client, cc_catalog, db_session):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.delete("/credit-card-statements", headers=headers)
    assert r.status_code == 204
    assert client.get("/credit-card-statements", headers=headers).status_code == 404
    assert db_session.execute(select(StagingCreditCardItem)).scalars().all() == []  # cascade
    # se puede cargar de nuevo
    assert client.post("/credit-card-statements", json=_payload(), headers=headers).status_code == 201


def test_delete_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    assert client.delete("/credit-card-statements", headers=headers).status_code == 404


# ---- acknowledge ----

def test_acknowledge_200(client, cc_catalog):
    headers = _auth(client)
    posted = _post_staging(client, headers)
    assert posted["review_findings"] == ["new_card"]  # sin tarjeta -> hay finding
    r = client.post("/credit-card-statements/acknowledge", json={}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert "items" not in body


def test_acknowledge_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    assert client.post("/credit-card-statements/acknowledge", json={}, headers=headers).status_code == 404


def test_acknowledge_409_no_findings(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    client.post("/credit-card-statements/acknowledge", json={}, headers=headers)  # limpia findings
    r = client.post("/credit-card-statements/acknowledge", json={}, headers=headers)  # ya no hay
    assert r.status_code == 409
    assert r.json()["code"] == "statement_has_no_findings"


def test_acknowledge_then_get_stays_clean(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    client.post("/credit-card-statements/acknowledge", json={}, headers=headers)
    body = client.get("/credit-card-statements", headers=headers).json()
    assert body["review_findings"] == []  # el GET no re-corre el reviewer (que volvería a poner new_card)
    assert body["is_ready"] is True


def test_chicos_401(client, cc_catalog):
    assert client.get("/credit-card-statements").status_code == 401
    assert client.delete("/credit-card-statements").status_code == 401
    assert client.post("/credit-card-statements/acknowledge", json={}).status_code == 401
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statements.py -q
```

- [ ] **Step 3: Agregar al servicio** `app/services/credit_card_statement_service.py`. Ampliar imports:

```python
from datetime import datetime, timezone

from sqlalchemy import delete, select, update  # 'update' es nuevo
```

(El `from datetime import datetime, timezone` va con los imports de arriba; `update` se suma al import de
sqlalchemy que ya trae `delete, select`.)

Funciones nuevas (al final del módulo):

```python
def get_staging_statement(
    db: Session, user: User
) -> tuple[StagingCreditCard, list[StagingCreditCardItem]]:
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id)
    ).scalar_one_or_none()
    if madre is None:
        raise AppError(ErrorCode.not_found)
    items = db.execute(
        select(StagingCreditCardItem).where(StagingCreditCardItem.staging_credit_card_id == madre.id)
    ).scalars().all()
    return madre, list(items)


def delete_staging_statement(db: Session, user: User) -> None:
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id)
    ).scalar_one_or_none()
    if madre is None:
        raise AppError(ErrorCode.not_found)
    db.delete(madre)  # ítems por ON DELETE CASCADE
    db.commit()


def acknowledge_staging_statement(db: Session, user: User) -> StagingCreditCard:
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id).with_for_update()
    ).scalar_one_or_none()
    if madre is None:
        raise AppError(ErrorCode.not_found)
    if madre.review_findings == "[]":
        raise AppError(ErrorCode.statement_has_no_findings)
    # UPDATE puntual; updated_at se preserva (reconocer no es cambio de negocio).
    db.execute(
        update(StagingCreditCard)
        .where(StagingCreditCard.id == madre.id)
        .values(
            review_findings="[]",
            user_acknowledged_at=datetime.now(timezone.utc),
            is_ready=True,
            updated_at=madre.updated_at,
        )
    )
    db.commit()
    db.refresh(madre)
    return madre
```

- [ ] **Step 4: Agregar los endpoints al router** `app/routers/credit_card_statements.py` (después de los PUT;
  `StagingStatementOut` y `StagingMadreOut` ya están importados):

```python
@router.get("/credit-card-statements", response_model=StagingStatementOut)
def get_staging_statement(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StagingStatementOut:
    madre, items = credit_card_statement_service.get_staging_statement(db, user)
    return StagingStatementOut.from_model(madre, items)


@router.delete("/credit-card-statements", status_code=status.HTTP_204_NO_CONTENT)
def delete_staging_statement(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    credit_card_statement_service.delete_staging_statement(db, user)


@router.post("/credit-card-statements/acknowledge", response_model=StagingMadreOut)
def acknowledge_staging_statement(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StagingMadreOut:
    return StagingMadreOut.from_model(
        credit_card_statement_service.acknowledge_staging_statement(db, user)
    )
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statements.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/core/errors.py app/services/credit_card_statement_service.py app/routers/credit_card_statements.py tests/test_credit_card_statements.py && git commit -m "feat: GET/DELETE/acknowledge staging-credit-card-statements"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (370 previos + los nuevos).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/staging-credit-card-statements-chicos` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** GET (200, 404, refleja PUT, no re-revisa); DELETE (204 + cascade + recarga, 404);
  acknowledge (200, 404, 409 por doble-ack, no re-revisa vía GET); 401 en los tres. ✓
- **Sin placeholders:** code nuevo, 3 funciones de servicio, 3 endpoints y tests completos. ✓
- **Consistencia:** acknowledge preserva `updated_at` con Core `update().values(updated_at=madre.updated_at)`
  (patrón `acknowledge_obligation`); no corre reviewer ni motor; DELETE no toca definitivas; GET sin escritura.
  `StagingStatementOut`/`StagingMadreOut` reusados. ✓
