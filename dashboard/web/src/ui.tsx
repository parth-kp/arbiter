import type { ReactNode } from 'react'
import type { Loaded } from './api'

export function Async<T>({ state, children }: { state: Loaded<T>; children: (d: T) => ReactNode }) {
  if (state.loading && !state.data) return <p className="muted pad">Loading{'…'}</p>
  if (state.error) return <p className="banner fail">{state.error}</p>
  if (!state.data) return null
  return <>{children(state.data)}</>
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className={`stat ${tone ?? ''}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export function Bar({ value, tone = 'ink' }: { value: number; tone?: string }) {
  return (
    <span className="bar" aria-hidden="true">
      <span className={`bar-fill ${tone}`} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </span>
  )
}

export function Pill({ tone, children }: { tone: 'pass' | 'fail' | 'warn' | 'neutral'; children: ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children && <div>{children}</div>}
    </div>
  )
}

export function Json({ value }: { value: unknown }) {
  return <pre className="json">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>
}
