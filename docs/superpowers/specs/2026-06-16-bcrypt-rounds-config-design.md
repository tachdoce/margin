# bcrypt cost configurable — acelerar la suite de tests

## Problema

La suite de tests tarda **~2:11 (131,7s)** para 720 tests (~0,18s por test) y crece linealmente
con la cantidad de tests. La causa medida no es "tener muchos tests": es que el hash de password
con **bcrypt cost 12** cuesta **~250-270ms** y se paga en cada test que crea o autentica un
usuario. Cost 12 es correcto en producción (seguridad), pero en test no aporta nada.

### Medición (no estimación)

| Corrida | Tiempo |
|---|---|
| Baseline (cost 12) | 131,7s (2:11) |
| Experimento con cost 4 | 35,4s (0:35) |

- bcrypt: cost 12 → hash 273,8ms / verify 250,5ms; cost 4 → ~1ms cada uno.
- Bajar el cost a 4 **solo en test** recorta **~96s (73%)**: la suite pasa de 2:11 a ~0:35.

El experimento corrió la suite real completa (720 tests verdes) con un plugin temporal que no
tocó el repo, así que el ahorro es medido, no proyectado.

## Objetivo

Que el cost factor de bcrypt sea **configuración** (una sola fuente de verdad) en vez de un
literal hardcodeado, para que producción siga en 12 y el entorno de test use 4. Sin cambiar el
comportamiento de seguridad de producción.

## Fuera de alcance

- La palanca de mover `Base.metadata.create_all()` a un fixture `scope="session"` (ahorra solo
  ~3s; medido: 4,1ms × 720). Queda para otro plan si se quiere; este plan es **solo bcrypt** —
  el 96% del ahorro en 3 líneas.

## Arquitectura

Una sola fuente de verdad para el cost factor: un campo en `Settings`.

- `app/core/config.py` — agregar `bcrypt_rounds: int = 12` a `Settings`. Default 12 → prod y dev
  quedan idénticos a hoy (no hace falta setear nada).
- `app/core/security.py` — construir `pwd_context` con `bcrypt__rounds=settings.bcrypt_rounds`
  en vez del literal `12`.
- `tests/conftest.py` — setear `BCRYPT_ROUNDS=4` en el entorno **antes** de importar la app.

### El detalle de orden de importación (la única parte con truco)

`pwd_context` se construye **al importar** `security.py`, leyendo `settings.bcrypt_rounds` una
sola vez. Y `settings` se congela al importar `config.py`. Por lo tanto, para que el test consiga
cost 4, la variable `BCRYPT_ROUNDS=4` tiene que estar en el entorno **antes** de que Python
importe la app.

El lugar es la **primera línea de `conftest.py`**, antes de cualquier `from app...`:

```python
import os
os.environ.setdefault("BCRYPT_ROUNDS", "4")
# ... recién después, los imports de la app
```

`pydantic-settings` le da prioridad a la variable de entorno por encima del `.env`, así que
prod/dev quedan en 12 sin tocar nada. `setdefault` deja override manual posible (ej. correr la
suite con cost 12 exportando la env var) sin pisarlo.

## Flujo de datos

`BCRYPT_ROUNDS` (env) → `Settings.bcrypt_rounds` (al importar config) → `pwd_context`
(al importar security) → `hash_password` / `verify_password`. Una sola lectura por proceso.

## Testing (TDD)

El cost queda **embebido en el propio hash bcrypt**: un hash cost 4 empieza con `$2b$04$`, uno
cost 12 con `$2b$12$`. Eso permite un test determinístico, sin medir tiempos (nada flaky):

- `hash_password("x")` produce un hash cuyo cost embebido coincide con `settings.bcrypt_rounds`.
- En entorno de test `settings.bcrypt_rounds == 4`, así que el hash empieza con `$2b$04$`.

La suite completa verde después del cambio es la verificación de que bajar el cost no rompe nada
(el round-trip hash/verify sigue funcionando con cualquier cost válido).

## Seguridad

Producción **no cambia**: sin la env var, el default es 12, idéntico a hoy. El cost factor pasa
a ser configurable, lo que además habilita subirlo en el futuro sin tocar código. bcrypt acepta
rounds 4–31; 4 es el mínimo válido y solo se usa en test.
