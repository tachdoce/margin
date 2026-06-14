import { getBootstrap } from './api'

function currency(currencyId) {
  return getBootstrap()?.catalogs?.currencies?.find((c) => c.id === currencyId) ?? null
}

// Nombre de la moneda (para labels/selects). "—" si no se conoce.
export function currencyName(currencyId) {
  return currency(currencyId)?.name ?? (currencyId == null ? '—' : `#${currencyId}`)
}

// Moneda de curso legal por defecto (para formularios).
export function defaultCurrencyId() {
  const list = getBootstrap()?.catalogs?.currencies ?? []
  return (list.find((c) => c.is_legal_tender) ?? list[0])?.id ?? null
}

// Monto formateado con símbolo y decimales de la moneda. formatMoney("1000", 1) → "$ 1.000".
export function formatMoney(amount, currencyId) {
  if (amount === null || amount === undefined || amount === '') return ''
  const n = Number(amount)
  if (Number.isNaN(n)) return String(amount)
  const cur = currency(currencyId)
  const decimals = cur?.display_decimals ?? 2
  const formatted = new Intl.NumberFormat('es-UY', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n)
  return cur?.symbol ? `${cur.symbol} ${formatted}` : formatted
}

// Monto redondeado sin decimales, con símbolo. Para tarjetas grandes del dashboard.
export function money0(amount, currencyId) {
  if (amount === null || amount === undefined || amount === '') return ''
  const n = Math.round(Number(amount))
  if (Number.isNaN(n)) return String(amount)
  const cur = currency(currencyId)
  const formatted = new Intl.NumberFormat('es-UY').format(n)
  return cur?.symbol ? `${cur.symbol} ${formatted}` : formatted
}

const MESES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]

// "2026-08" → "agosto 2026". Sin valor → "".
export function monthName(key) {
  if (!key) return ''
  const [y, m] = key.split('-')
  const idx = Number(m) - 1
  return MESES[idx] ? `${MESES[idx]} ${y}` : key
}

// "2026-08" → "Ago". Para el timeline compacto.
export function monthShort(key) {
  if (!key) return ''
  const m = Number(key.split('-')[1]) - 1
  const short = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
  return short[m] ?? key
}
