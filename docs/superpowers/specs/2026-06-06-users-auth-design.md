# Users + Auth — Diseño (registro y login)

> **Qué es este documento.** El diseño de la feature de identidad y autenticación del backend.
> El *qué* del producto y los contratos detallados viven en Notion (Backend → Endpoints → Usuarios,
> y Backend → Endpoints → GLOBAL). Este spec consolida esas decisiones + las de implementación.

- **Fecha:** 2026-06-06
- **Estado:** aprobado para implementar
- **Depende de:** la foundation del backend (FastAPI + SQLAlchemy + Alembic + `countries`), ya en `main`.

---

## 1. Alcance

Dos endpoints públicos (exentos de Bearer token, regla en Notion → GLOBAL):

- `POST /auth/register`
- `POST /auth/login`

MVP: login solo por **email + password**.

**Diferido al TODO** (documentado, no se construye ahora): verificación de email, recuperación
y cambio de contraseña, logout server-side, refresh token, login con Google (provider federado).

---

## 2. Contrato de la API (fuente: Notion)

### POST /auth/register
- **Body:** `{ email: str, password: str, display_name?: str }`
- **201:** `{ "user": { "id", "country_code", "display_name" }, "token": "<jwt>" }` (auto-login)
- `country_code` **no** viene en el body: el backend lo fija en `'UY'` (MVP).
- Errores: `email_invalid` (422), `password_too_short` (422), `email_already_registered` (409).

### POST /auth/login
- **Body:** `{ email: str, password: str }`
- **200:** `{ "user": { "id", "country_code", "display_name" }, "token": "<jwt>" }`
- Errores: `credentials_invalid` (401, mensaje único que no revela la causa), `validation_failed` (422) si faltan campos.

### Objeto `user`
Solo `id`, `country_code`, `display_name`. **Nunca** `created_at`/`updated_at` ni nada de `auth_identities`.
El password jamás se persiste ni se devuelve en claro.

---

## 3. Modelos de datos

`countries` ya existe (FK destino). Se crean dos modelos + un enum.

### users
| columna | tipo | null | notas |
|---|---|---|---|
| id | uuid PK | no | |
| country_code | varchar(2) FK→countries | no | **sin DEFAULT en la tabla.** Lo inserta el servicio (hoy `'UY'` fijo; a futuro, el país que elija el usuario) |
| display_name | varchar(80) | sí | opcional |
| deleted_at | timestamp | sí | **soft-delete** (NULL = vigente) |
| created_at | timestamp | no | |
| updated_at | timestamp | no | |

### auth_identities
| columna | tipo | null | notas |
|---|---|---|---|
| id | uuid PK | no | |
| user_id | uuid FK→users | no | |
| provider | enum `auth_provider` | no | hoy solo `email` |
| identifier | varchar(255) | no | email normalizado (lowercase + trim) |
| password_hash | varchar(255) | sí | bcrypt; NULL para providers federados |
| created_at | timestamp | no | |
| updated_at | timestamp | no | |

- **Unique (provider, identifier)**.
- Enum: `CREATE TYPE auth_provider AS ENUM ('email')`. Crece sin migración de esquema al sumar `google`.
  **Excepción documentada:** valores del enum en inglés (nombres técnicos de proveedores), no en español.
- Migración Alembic crea el enum + las dos tablas. Se registran los modelos en `app/models/__init__.py`.

---

## 4. Seguridad

- **Hash de password:** bcrypt **cost 12** vía `passlib`. La contraseña en claro nunca se persiste.
- **JWT:** `python-jose`, algoritmo **HS256**, payload con `user_id` (el id de `users`) y `exp`.
  Vigencia larga (config, **45 días** por defecto, dentro del rango 30–60 de Notion). **Sin refresh token.**
- **Config nueva** en `Settings` / `.env.example`: `SECRET_KEY` (obligatoria, sin default real en `.env.example`)
  y `jwt_expire_days` (default 45). `SECRET_KEY` no se commitea.
- **Nuevas dependencias:** `passlib[bcrypt]`, `python-jose[cryptography]`.

---

## 5. Arquitectura por capas

Esta feature introduce la **capa de servicio** (lógica de negocio separada del router):

| archivo | responsabilidad |
|---|---|
| `app/schemas/auth.py` | Pydantic de request/response (solo estructura: campos presentes y tipos) |
| `app/services/auth_service.py` | lógica: normalizar, validar, hashear, crear en transacción, emitir token; lanza `AppError` |
| `app/routers/auth.py` | finito: recibe el body, llama al servicio, devuelve el response |
| `app/core/security.py` | hash de password (passlib) + emisión/decodificación de JWT (jose) |
| `app/core/errors.py` | catálogo de error codes + `AppError` + registro de handlers |

El router no contiene reglas de negocio. El servicio no conoce HTTP (lanza `AppError`, no `HTTPException`).

---

## 6. Manejo de errores (transversal)

Formato de error de Notion → GLOBAL (se respeta tal cual):
- Singular: `{ "code", "message", "field"? }`
- Múltiple: `{ "code": "validation_failed", "message", "errors": [ {code, message, field}, ... ] }`

### Implementación
1. **Catálogo central** (`app/core/errors.py`): cada code define su `status` HTTP y su `message` (espeja
   el "Catálogo de error codes" de Notion). Única fuente de verdad de codes/mensajes.
2. **`AppError`**: excepción que el servicio lanza por code (status y message salen del catálogo); acepta `field` opcional.
3. **Handlers globales** registrados en la app:
   - `AppError` → `{code, message, field?}` con su status.
   - `RequestValidationError` (Pydantic: campos faltantes/mal tipados) → wrapper `validation_failed` (422).
   - `Exception` no controlada → 500 `{code: "internal_error", message: "Ocurrió un error. Intentá de nuevo."}`.

### Validación manual en el servicio (en orden, con los codes del catálogo)
- **register:** formato de email (`email_invalid` 422) → normalizar (`strip().lower()`) → password ≥ 8 sin trim
  (`password_too_short` 422) → no existe identity con (`email`, ese email) (`email_already_registered` 409).
- **login:** campos presentes (Pydantic → `validation_failed` 422) → normalizar → buscar identity por
  (`provider='email'`, identifier) → verificar password contra el hash → `users.deleted_at` IS NULL.
  **Cualquier fallo de los últimos tres pasos → `credentials_invalid` (401)**, mensaje único que no
  revela si fue email inexistente, password incorrecta o cuenta dada de baja.

### Codes de auth (del catálogo)
| code | status | message |
|---|---|---|
| `unauthenticated` | 401 | "Sesión inválida o expirada." |
| `credentials_invalid` | 401 | "Credenciales inválidas." |
| `email_already_registered` | 409 | "Ese email ya está registrado." |
| `email_invalid` | 422 | "Email inválido." |
| `password_too_short` | 422 | "La contraseña debe tener al menos 8 caracteres." |
| `validation_failed` | 422 | "Hay errores en el formulario." |

(`unauthenticated` se incluye en el catálogo para la base de errores, aunque su uso —proteger endpoints—
recién aparece con la primera ruta autenticada, fuera de esta feature.)

---

## 7. Diferido y documentado: el plan default

Notion (`POST register`) especifica que el registro crea, en la misma transacción, también un `plans`
default (`is_default=true`, "Mi plan actual", dial 0, moneda derivada del país). **Se difiere**, porque
depende de las tablas `plans` y `currencies` (aún inexistentes).

**No cambia el contrato externo:** el response de `/auth/register` es `{user, token}` con o sin plan default
— el plan es un efecto interno que el cliente no ve. Se agregará a la transacción del registro cuando se
construya el subdominio de flujo de dinero. Queda anotado como pendiente.

---

## 8. Testing (TDD por endpoint)

- **register:** OK (201, devuelve user + token, crea user + identity, hash ≠ password en claro);
  `email_invalid`; `password_too_short`; `email_already_registered`.
- **login:** OK (200, user + token); `credentials_invalid` en los tres casos (email inexistente,
  password incorrecta, user soft-deleted).
- **errores/handlers:** un `AppError` rinde `{code, message, field?}` con el status correcto;
  un campo faltante rinde `validation_failed` (422).
- **token:** el JWT emitido decodifica con `SECRET_KEY` y trae el `user_id` correcto.
- Reusa el harness existente (`db_session` sobre `margin_test` + `client` con override de `get_db`).

---

## 9. Decisiones, con su porqué

- **Capa de servicio** separada del router: el endpoint queda finito y testeable; la lógica de negocio
  no conoce HTTP (lanza `AppError`). Reusable cuando entren más endpoints.
- **Catálogo central de errores + handlers globales:** codes/mensajes en un solo lugar (sincronizado con
  Notion), y ningún error se escapa del formato del contrato (ni los crashes).
- **Validación manual en el servicio:** control fino del code, mensaje y orden exactos del catálogo,
  en vez del shape automático de Pydantic.
- **`credentials_invalid` único en login:** no revelar si el email existe o si la cuenta está de baja
  (no dar información a un atacante).
- **`country_code` sin DEFAULT en la tabla:** el valor lo inserta el servicio (hoy `'UY'` fijo), no la BD.
  Así, cuando el usuario pueda elegir su país, solo cambia la lógica del servicio y el esquema queda intacto;
  evita hornear un sesgo a Uruguay en la base.
- **JWT largo sin refresh (MVP):** simplicidad; el refresh se difiere. Decisión de Notion.
- **Plan default diferido:** ver sección 7.
