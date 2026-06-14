# Margin · web2 (prototipo del producto)

Front-end **orientado al usuario** (no banco de pruebas) que consume el mismo backend que `/web`.
Vue 3 + Vite, mobile-first. Foco en el loop central: cargar deudas/ingresos → armar/elegir un
plan → organizar pagos → ver el timeline con los hitos de salud financiera.

> Prototipo en curso. La app móvil real vive en otro repo; esto es la versión web del producto.

## Correr

```bash
cp .env.example .env          # apuntar a tu backend (default http://localhost:8000)
npm install
npm run dev                   # http://localhost:5174
```

Requiere el backend corriendo (ver `backend/`). El `/web` (banco de pruebas) no se toca.

## Estructura

- `src/api/` — cliente fetch del backend + sesión en localStorage (mismo contrato que `/web`).
- `src/router/` — rutas + guard de auth.
- `src/pages/` — una pantalla por sección: `Login`, `Hoy`, `Finanzas`, `Plan`, `Perfil`.
- `src/components/` — `AppShell` (marco mobile + bottom-nav), `BottomNav`, `Sheet` (hoja inferior).
- `src/style.css` — design system mobile-first (Inter, índigo).

## Navegación (bottom-nav)

`Hoy` (resumen + salud) · `Finanzas` (ingresos y deudas) · `Plan` (estrategia + futuro) · `Perfil`.
