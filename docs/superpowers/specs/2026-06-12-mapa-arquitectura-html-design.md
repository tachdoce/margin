# Mapa de arquitectura — HTML autocontenido — Diseño

## Objetivo

Generar un único archivo HTML autocontenido que muestre, de forma gráfica, la arquitectura del backend Margin a un colega: por cada dominio, sus **endpoints**, sus **servicios** y sus **modelos** (vista por capas Router → Service → Model). Pensado para mandar el archivo y abrirlo con doble click, sin backend ni `npm`.

## Decisiones de diseño (cerradas en brainstorming)

- **Vista C** (por capas), no diagrama ER de relaciones (FKs).
- **Archivo HTML separado y autocontenido** (no una pestaña en `/web`, no fetch en vivo). Datos *inline* en el HTML.
- **Generado por un script** en `tools/arch_map/`. Regenerable con un comando cuando el código cambia.
- Los **endpoints** se sacan del esquema OpenAPI de la app (snapshot al momento de generar). Las capas **service/model** salen de un mapa curado a mano.

## Arquitectura

Dos piezas en `tools/arch_map/`:

### 1. Mapa curado de dominios — `tools/arch_map/domains.py`

Un dict que asocia cada `tag` de OpenAPI con su etiqueta legible, sus servicios y sus modelos. Es el único dato a mano (~16 dominios, pocas líneas cada uno). Forma:

```python
DOMAINS = {
    "plans": {
        "label": "Planes",
        "services": ["plan_service.py", "planning/engine.py"],
        "models": ["Plan", "PlanMovement"],
    },
    "cash-flow-payments": {
        "label": "Flujo de caja · pagos",
        "services": ["cash_flow_payment_service.py", "cash_flow/*"],
        "models": ["CashFlowPayment", "CashFlowEntry"],
    },
    # ... un entry por cada tag (auth, bootstrap, cash-balances, cash-flow-entries,
    #     countries, credit-card-statements, credit-cards, debts, expenses,
    #     financings, incomes, obligations, plan_movements, purchases)
}

# Orden de presentación de los dominios en la página (los principales primero).
ORDER = ["plans", "plan_movements", "cash-flow-entries", "cash-flow-payments",
         "credit-cards", "credit-card-statements", "debts", "expenses",
         "incomes", "financings", "purchases", "obligations", "cash-balances",
         "auth", "bootstrap", "countries"]
```

Reglas:
- La clave es el `tag` exacto que usa el router (verificable en `app/routers/*.py`).
- `services`/`models` son strings descriptivos (nombre de archivo o clase), no imports reales — es documentación visual.
- Un tag presente en OpenAPI pero ausente del mapa se renderiza igual, con services/models vacíos y un aviso visual (para no esconder dominios nuevos). Endpoints sin tag (ej. `/health`) van a un grupo "Otros".
- Los nombres de `services`/`models` se verifican contra `app/services/` y `app/models/` al escribir el mapa (son strings curados, no imports).

### 2. Generador — `tools/arch_map/build.py`

Pasos:
1. `from app.main import app; schema = app.openapi()` — no requiere server corriendo (verificado: 64 operaciones, con `method`, `path`, `tags`, `summary`).
2. Recorrer `schema["paths"]` → por cada `(path, method)` extraer `tags[0]` (o `"_otros"` si no hay tag), `summary` y el `method` en mayúsculas.
3. Agrupar endpoints por tag.
4. Fusionar con `DOMAINS`: para cada tag en `ORDER` (más los tags extra que aparezcan en OpenAPI y no estén en `ORDER`, al final), construir la lane con sus endpoints + services + models.
5. Renderizar el HTML con los datos *inline* (CSS + el marcado de las lanes embebidos; sin JS imprescindible — el filtro por dominio es un plus opcional con un `<script>` chico inline).
6. Escribir el resultado a `tools/arch_map/arquitectura.html`.

Uso: `cd backend && ../.venv/bin/python ../tools/arch_map/build.py` (o equivalente; la ruta exacta del intérprete/CWD se fija en el plan). Imprime la ruta del archivo escrito.

## El HTML resultante

- Encabezado: título "Margin · Mapa de arquitectura" y una leyenda de colores por método (GET verde, POST azul, PATCH ámbar, DELETE rojo).
- Una **lane por dominio**, en el orden de `ORDER`. Cada lane:
  - **Router (arriba):** nombre del dominio + chips de endpoints, uno por endpoint, coloreado por método, con el método y el path (`POST /plans`). Tooltip/título = summary.
  - **▼ Service (medio):** los archivos de `services`.
  - **▼ Model (abajo):** las clases de `models`.
- Estilo oscuro tipo el de los mockups (no hace falta reusar tokens de `/web`: es un archivo aparte). CSS inline, sin dependencias externas (sin CDNs) para que funcione 100% offline.
- Pie: contador de dominios y de endpoints totales, y la fecha de generación (la pasa el generador como string; no usar `datetime.now()` en el HTML).

## Qué NO incluye (YAGNI)

- Sin diagrama de relaciones/FKs (era la opción A, descartada).
- Sin backend nuevo, sin endpoint, sin cambios en `app/`.
- Sin fetch en vivo: es un snapshot.
- Sin integración con `/web`.

## Testing

El generador es un script de presentación, no lógica de negocio; el repo no tiene suite para `tools/`. Verificación manual, documentada en el plan:
1. Correr `build.py` → escribe `arquitectura.html` sin error.
2. Abrir el HTML en el navegador → se ven las ~16 lanes, los 64 endpoints repartidos por dominio y coloreados por método, y las capas service/model.
3. Chequear que ningún tag de OpenAPI quede sin lane (ni `/health`).

Como guardas automáticas mínimas dentro de `build.py` (baratas y útiles): tras construir, **assert** que (a) la suma de endpoints renderizados == total de operaciones en OpenAPI (nada se pierde al agrupar) y (b) todo tag de OpenAPI tiene una lane. Si fallan, el script aborta con un mensaje claro.

## Artefacto y git

`tools/arch_map/arquitectura.html` es un artefacto generado: se agrega a `.gitignore` (se regenera on-demand). Se versionan `build.py` y `domains.py`. También agregar `.superpowers/` al `.gitignore` si no está (quedó del companion visual de brainstorming).
