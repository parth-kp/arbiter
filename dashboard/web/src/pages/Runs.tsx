import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useApi } from '../api'
import { Async, Empty, Pill } from '../ui'
import { date, flag, money, pct, pctCi, dash } from '../format'
import type { RunRow } from '../types'

export default function Runs() {
  const state = useApi<RunRow[]>('/api/runs')
  const [env, setEnv] = useState('')
  const [sel, setSel] = useState<string[]>([])
  const nav = useNavigate()

  const rows = useMemo(() => {
    const all = state.data ?? []
    return all.filter(r => !env || r.environment === env).sort((a, b) => b.created_at.localeCompare(a.created_at))
  }, [state.data, env])
  const envs = useMemo(() => [...new Set((state.data ?? []).map(r => r.environment))].sort(), [state.data])

  const toggle = (id: string) =>
    setSel(s => (s.includes(id) ? s.filter(x => x !== id) : s.length >= 2 ? [s[1], id] : [...s, id]))

  const compare = () => {
    const picked = (state.data ?? []).filter(r => sel.includes(r.id)).sort((a, b) => a.created_at.localeCompare(b.created_at))
    nav(`/compare?a=${encodeURIComponent(picked[0].id)}&b=${encodeURIComponent(picked[1].id)}`)
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Runs</h1>
          <p className="muted">Each run is one agent configuration evaluated on one scenario set.</p>
        </div>
        <div className="toolbar">
          <label className="field">
            Environment
            <select value={env} onChange={e => setEnv(e.target.value)}>
              <option value="">All</option>
              {envs.map(e => <option key={e}>{e}</option>)}
            </select>
          </label>
          <button className="btn primary" disabled={sel.length !== 2} onClick={compare}>
            Compare{sel.length === 2 ? '' : ` (${sel.length}/2)`}
          </button>
        </div>
      </div>
      <Async state={state}>
        {() =>
          rows.length === 0 ? (
            <Empty title="No runs yet">
              Run <code>arbiter run</code> and commit the result under <code>results/runs</code>, then restart the dashboard.
            </Empty>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th />
                    <th>Date</th>
                    <th>Environment</th>
                    <th>Label</th>
                    <th>Agent</th>
                    <th>Model</th>
                    <th>Prompt</th>
                    <th>Retr.</th>
                    <th>Inj. def.</th>
                    <th className="num">Success (95% CI)</th>
                    <th className="num">pass^k</th>
                    <th className="num">Violations</th>
                    <th className="num">Attempts</th>
                    <th className="num">$/conv</th>
                    <th className="num">$/success</th>
                    <th className="num">Spend</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => {
                    const spend = r.spend ? Object.values(r.spend).reduce((a, b) => a + b, 0) : null
                    return (
                      <tr key={r.id} className={sel.includes(r.id) ? 'selected' : ''}>
                        <td>
                          <input type="checkbox" aria-label={`Select ${r.id}`} checked={sel.includes(r.id)} onChange={() => toggle(r.id)} />
                        </td>
                        <td className="nowrap"><Link to={`/runs/${r.id}`}>{date(r.created_at)}</Link></td>
                        <td>{r.environment}</td>
                        <td>{r.label || dash}</td>
                        <td>{r.agent_type}</td>
                        <td className="mono">{r.model ?? dash}</td>
                        <td className="mono">{r.prompt_version ?? dash}</td>
                        <td><Pill tone="neutral">{flag(r.retrieval)}</Pill></td>
                        <td><Pill tone="neutral">{flag(r.injection_defense)}</Pill></td>
                        <td className="num mono nowrap">{pctCi(r.success_rate, r.success_ci95)}</td>
                        <td className="num mono">{pct(r.pass_hat_k)}</td>
                        <td className={`num mono ${r.violation_rate ? 'bad' : ''}`}>{pct(r.violation_rate)}</td>
                        <td className="num mono">{pct(r.attempt_rate)}</td>
                        <td className="num mono">{money(r.cost_per_conversation)}</td>
                        <td className="num mono">{money(r.cost_per_success)}</td>
                        <td className="num mono" title={r.spend ? JSON.stringify(r.spend) : undefined}>{money(spend)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <p className="muted small">Baseline is the older of the two selected runs.</p>
            </div>
          )
        }
      </Async>
    </>
  )
}
