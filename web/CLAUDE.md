# Web (Margin) — banco de pruebas

Vue 3 + Vite + Vue Router. Cliente de prueba del backend (no es la app móvil real, que es otro repo).
Usa el estilo del design-system (Inter, índigo, mobile-first 390px).

## Comandos
- Dev: `npm run dev`  (http://localhost:5173)
- Build: `npm run build`
- Requiere el backend corriendo en la URL de `VITE_API_BASE_URL` (ver `.env`).

## Estructura (sección 5 del spec de estructura)
- `src/api/` — cliente fetch del backend + sesión en localStorage. URL base desde `VITE_API_BASE_URL`.
- `src/router/` — rutas + guard (las no-públicas exigen token).
- `src/pages/` — una página por pantalla (Login, Register, Dashboard).
- `src/style.css` — tokens del design-system + componentes.

## Convenciones
- URL del backend NUNCA hardcodeada: sale de `import.meta.env.VITE_API_BASE_URL`.
- Errores del backend: el cliente parsea `{code, message, field?}` y la página muestra `message`.
- Token + user en `localStorage` (cliente de prueba en dev; no es producción).
