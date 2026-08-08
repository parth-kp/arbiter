import type { Ci } from './types'

export const dash = '—'

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return dash
  return v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`
}

export function pct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return dash
  return `${(v * 100).toFixed(1)}%`
}

export function pctCi(v: number | null | undefined, ci: Ci | null | undefined): string {
  if (v === null || v === undefined) return dash
  return ci ? `${pct(v)} [${(ci[0] * 100).toFixed(1)}, ${(ci[1] * 100).toFixed(1)}]` : pct(v)
}

export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined) return dash
  return v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`
}

export function num(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return dash
  return v.toFixed(digits)
}

export function signedPp(v: number | undefined): string {
  if (v === undefined) return dash
  const pp = v * 100
  return `${pp > 0 ? '+' : ''}${pp.toFixed(1)} pp`
}

export function date(s: string): string {
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function shortId(id: string): string {
  return id.length > 14 ? id.slice(0, 12) + '…' : id
}

export function flag(v: unknown): string {
  if (v === null || v === undefined) return dash
  if (v === true) return 'on'
  if (v === false) return 'off'
  return String(v)
}

export function flatten(obj: unknown, prefix = '', out: Record<string, string> = {}): Record<string, string> {
  if (obj !== null && typeof obj === 'object' && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj)) flatten(v, prefix ? `${prefix}.${k}` : k, out)
  } else {
    out[prefix] = typeof obj === 'string' ? obj : JSON.stringify(obj)
  }
  return out
}
