import { Link, useParams } from 'react-router-dom'
import { useApi } from '../api'
import { Async, Bar, Empty } from '../ui'
import { pct } from '../format'
import type { FailurePattern } from '../types'

const roleLabel: Record<string, string> = { user: 'USER', assistant: 'ASSISTANT', tool: 'TOOL ERROR', tool_call: 'CALL', error: 'ERROR' }

export default function Failures() {
  const { id = '' } = useParams()
  const state = useApi<FailurePattern[]>(`/api/runs/${encodeURIComponent(id)}/failures`)
  return (
    <>
      <div className="crumbs"><Link to="/">Runs</Link> / <Link to={`/runs/${encodeURIComponent(id)}`} className="mono">{id}</Link> / Failures</div>
      <div className="page-head"><div><h1>Failure patterns</h1><p className="muted">Failed trials grouped by their most important failed check, ranked by count.</p></div></div>
      <Async state={state}>
        {ps =>
          ps.length === 0 ? <Empty title="No failures">Every trial in this run succeeded.</Empty> : (
            <div className="patterns">
              {ps.map((p, i) => (
                <article className="pattern" key={p.reason}>
                  <header>
                    <span className="rank">{i + 1}</span>
                    <h2 className="mono">{p.reason}</h2>
                    <span className="count bad">{p.count} trial{p.count === 1 ? '' : 's'}</span>
                  </header>
                  <div className="share"><Bar value={p.share} tone="fail" /><span className="mono small">{pct(p.share)} of failures</span></div>
                  <dl className="kv">
                    <dt>Categories</dt><dd>{p.categories.join(', ')}</dd>
                    <dt>Scenarios</dt>
                    <dd className="chips-inline">{p.scenarios.map(s => <Link key={s} className="mono" to={`/runs/${encodeURIComponent(id)}/scenarios/${encodeURIComponent(s)}`}>{s}</Link>)}</dd>
                    {p.top_details.length > 0 && (
                      <>
                        <dt>Top details</dt>
                        <dd><ul className="plain">{p.top_details.map(([d, n]) => <li key={d}><span className="mono small">{n}×</span> {d}</li>)}</ul></dd>
                      </>
                    )}
                  </dl>
                  {p.examples.map(ex => (
                    <details className="example" key={`${ex.scenario_id}-${ex.trial_index}`}>
                      <summary>
                        <span className="mono">{ex.scenario_id}</span> trial {ex.trial_index}
                      </summary>
                      <ul className="excerpt">
                        {ex.excerpt.map((l, j) => <li key={j} className={l.role}><b>{roleLabel[l.role] ?? l.role}</b><span>{l.text}</span></li>)}
                      </ul>
                      <p className="small">
                        <Link to={`/runs/${encodeURIComponent(ex.run_id)}/scenarios/${encodeURIComponent(ex.scenario_id)}`}>Full trial</Link>
                        {ex.trace_id && <> &middot; <Link to={`/traces/${encodeURIComponent(ex.trace_id)}`}>Trace</Link></>}
                      </p>
                    </details>
                  ))}
                </article>
              ))}
            </div>
          )
        }
      </Async>
    </>
  )
}
