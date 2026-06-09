import { getBootstrap } from './api'

function currency(currencyId) {
  return getBootstrap()?.catalogs?.currencies?.find((c) => c.id === currencyId) ?? null
}

// Nombre de la moneda (para labels/selects). "—" si no se conoce.
export function currencyName(currencyId) {
  return currency(currencyId)?.name ?? (currencyId == null ? '—' : `#${currencyId}`)
}

// Monto formateado con el símbolo y los decimales de la moneda (metadata del catálogo).
// Ej: formatMoney("1000", 1) → "$ 1.000" ; formatMoney("50.00", 3) → "U$S 50,00".
// Si falta el monto → "". Si no se conoce la moneda → el monto crudo.
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
