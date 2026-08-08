import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../api'
import { Async, Empty } from '../ui'
import { flatten, pct, shortId, signedPp, dash } from '../format'
import type { CompareResponse, Paired, RunDetail } from '../types'

const METRICS: { key: string; label: string; lowerBetter: boolean }[] = [
  { key: 'success', label: 'Success rate', lowerBetter: false },
  { key: 'violation', label: 'Policy violation rate', lowerBetter: true },
  { key: 'attempt', label: 'Policy attempt rate', lowerBetter: true },
]

function Row({ label, p, lowerBetter, sub }: { label: string; p: Paired | undefined; lowerBetter: boolean; sub?: boolean }) {
  if (!p || !p.n) {
    return <tr><td className={sub ? 'indent' : ''}>{label}</td><td colSpan={6} className="muted">no common scenarios</td></tr>
  }
  const d = p.delta ?? 0
  const tone = Math.abs(d) < 1e-9 ? '' : (d > 0) !== lowerBetter ? 'good' : 'bad'
  return (
    <tr>
      <td className={sub ? 'indent' : ''}>{label}</td>
      <td className="num mono">{p.n}</td>
      <td className="num mono">{pct(p.baseline)}</td>
      <td className="num mono">{pct(p.candidate)}</td>
      <td className={`num mono ${tone}`}>
        {signedPp(p.delta)}
        {p.delta_ci95 && <span className="muted small"> [{(p.delta_ci95[0] * 100).toFixed(1)}, {(p.delta_ci95[1] * 100).toFixed(1)}]</span>}
      </td>
      <td className="num mono">{p.p_value !== undefined ? p.p_value.toFixed(4) : dash}</td>
      <td className={p.significant ? 'sig' : 'muted'}>{p.significant ? '● significant' : '○ n.s.'}</td>
    </tr>
  )
}

function ScenarioList({ ids, runId, empty }: { ids: string[]; runId: string; empty: string }) {
  if (!ids.length) return <p className="muted small">{empty}</p>
  return (
    <ul className="chips">
      {ids.map(s => (
        <li key={s}><Link className="mono" to={`/runs/${encodeURIComponent(runId)}/scenarios/${encodeURIComponent(s)}`}>{s}</Link></li>
      ))}
    </ul>
  )
}

export default function Compare() {
  const [q] = useSearchParams()
  const a = q.get('a') ?? ''
  const b = q.get('b') ?? ''
  const ok = Boolean(a && b)
  const cmp = useApi<CompareResponse>(ok ? `/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}` : null)
  const da = useApi<RunDetail>(ok ? `/api/runs/${encodeURIComponent(a)}` : null)
  const db = useApi<RunDetail>(ok ? `/api/runs/${encodeURIComponent(b)}` : null)

  if (!ok) return <Empty title="Pick two runs to compare"><Link to="/">Go to runs</Link> and tick two checkboxes.</Empty>

  const diffRows = () => {
    if (!da.data || !db.data) return null
    const fa = flatten({ environment: da.data.run.environment, agent_type: da.data.run.agent_type, ...da.data.config })
    const fb = flatten({ environment: db.data.run.environment, agent_type: db.data.run.agent_type, ...db.data.config })
    const keys = [...new Set([...Object.keys(fa), ...Object.keys(fb)])].sort()
    return keys.map(k => ({ k, a: fa[k], b: fb[k], diff: fa[k] !== fb[k] }))
  }
  const rows = diffRows()

  return (
    <Async state={cmp}>
      {({ a: ra, b: rb, comparison: c }) => (
        <>
          <div className="crumbs"><Link to="/">Runs</Link> / Compare</div>
          <div className="page-head">
            <div>
              <h1>Compare runs</h1>
              <p className="muted">
                Baseline <Link className="mono" to={`/runs/${encodeURIComponent(ra.id)}`}>{shortId(ra.id)}</Link> {ra.label && `(${ra.label})`} vs candidate{' '}
                <Link className="mono" to={`/runs/${encodeURIComponent(rb.id)}`}>{shortId(rb.id)}</Link> {rb.label && `(${rb.label})`}. Paired by scenario, sign-flip permutation test, {'α'}={c.alpha}.
              </p>
            </div>
          </div>

          <h2>Configuration</h2>
          {!rows ? <p className="muted">Loading{'…'}</p> : (
            <div className="table-wrap">
              <table className="data config">
                <thead><tr><th>Key</th><th>Baseline</th><th>Candidate</th></tr></thead>
                <tbody>
                  {[...rows.filter(r => r.diff), ...rows.filter(r => !r.diff)].map(r => (
                    <tr key={r.k} className={r.diff ? 'diff' : 'same'}>
                      <td className="mono">{r.k}</td>
                      <td className="mono">{r.a ?? dash}</td>
                      <td className="mono">{r.b ?? dash}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2>Metrics</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr><th>Metric / category</th><th className="num">Scenarios</th><th className="num">Baseline</th><th className="num">Candidate</th><th className="num">Delta [95% CI]</th><th className="num">p-value</th><th style={{ textTransform: 'none' }}>significance (α = {c.alpha})</th></tr>
              </thead>
              <tbody>
                {METRICS.map(m => (
                  <MetricBlock key={m.key} m={m} c={c} />
                ))}
              </tbody>
            </table>
          </div>

          <div className="two-col">
            <section>
              <h2>Newly failing <span className="count bad">{c.newly_failing.length}</span></h2>
              <ScenarioList ids={c.newly_failing} runId={rb.id} empty="No scenario dropped below 50% success." />
            </section>
            <section>
              <h2>Newly passing <span className="count good">{c.newly_passing.length}</span></h2>
              <ScenarioList ids={c.newly_passing} runId={rb.id} empty="No scenario rose above 50% success." />
            </section>
          </div>
          {(c.only_in_baseline.length > 0 || c.only_in_candidate.length > 0) && (
            <p className="muted small">
              Excluded (not in both runs): {c.only_in_baseline.length} only in baseline, {c.only_in_candidate.length} only in candidate.
            </p>
          )}
        </>
      )}
    </Async>
  )
}

function MetricBlock({ m, c }: { m: { key: string; label: string; lowerBetter: boolean }; c: CompareResponse['comparison'] }) {
  return (
    <>
      <Row label={m.label} p={c.metrics[m.key]} lowerBetter={m.lowerBetter} />
      {Object.entries(c.by_category).map(([cat, ms]) => (
        <Row key={cat} label={cat} p={ms[m.key]} lowerBetter={m.lowerBetter} sub />
      ))}
    </>
  )
}
