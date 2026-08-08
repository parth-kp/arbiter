import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useApi } from '../api'
import { Async, Json, Pill } from '../ui'
import Transcript from '../Transcript'
import { dash, money } from '../format'
import type { ScenarioDetail, Trial } from '../types'

function TrialView({ t, runId }: { t: Trial; runId: string }) {
  const agentCost = t.calls.filter(c => c.purpose === 'agent').reduce((s, c) => s + c.cost_usd, 0)
  const evalCost = t.calls.filter(c => c.purpose !== 'agent').reduce((s, c) => s + c.cost_usd, 0)
  const judges = t.checks.filter(c => c.kind === 'judge')
  const checks = t.checks.filter(c => c.kind !== 'judge')
  const stateKeys = Object.keys(t.state_diff ?? {})
  return (
    <div className="trial">
      <div className="stats compact">
        <div className="stat"><div className="stat-label">Outcome</div><div className="stat-value">{t.success ? <Pill tone="pass">success</Pill> : <Pill tone="fail">failed</Pill>}</div></div>
        <div className="stat"><div className="stat-label">Termination</div><div className="stat-value small-v">{t.termination}</div></div>
        <div className="stat"><div className="stat-label">Turns</div><div className="stat-value small-v mono">{t.turns}</div></div>
        <div className="stat"><div className="stat-label">Agent cost</div><div className="stat-value small-v mono">{money(agentCost)}</div></div>
        <div className="stat"><div className="stat-label">Eval overhead</div><div className="stat-value small-v mono">{money(evalCost)}</div></div>
        <div className="stat"><div className="stat-label">Trace</div><div className="stat-value small-v">
          {t.trace_url ? (t.trace_url.startsWith('/') ? <Link to={t.trace_url}>open waterfall</Link> : <a href={t.trace_url} target="_blank" rel="noreferrer">open in Langfuse</a>) : dash}
        </div></div>
      </div>
      {t.error && <p className="banner fail">{t.error}</p>}

      <div className="split">
        <section>
          <h3>Transcript</h3>
          <Transcript events={t.events} />
        </section>
        <aside>
          <h3>Final-state and policy checks</h3>
          {checks.length === 0 ? <p className="muted">No checks.</p> : (
            <table className="data tight">
              <thead><tr><th>Result</th><th>Kind</th><th>Check</th></tr></thead>
              <tbody>
                {checks.map((c, i) => (
                  <tr key={i}>
                    <td><Pill tone={c.passed ? 'pass' : c.required ? 'fail' : 'warn'}>{c.passed ? 'pass' : 'fail'}</Pill></td>
                    <td className="small">{c.kind}</td>
                    <td><div className="mono small">{c.name}{!c.required && <span className="muted"> (optional)</span>}</div>{c.detail && <div className="small muted">{c.detail}</div>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h3>Judge</h3>
          {judges.length === 0 ? <p className="muted small">No judge criteria for this scenario.</p> : judges.map((c, i) => (
            <div className={`judge ${c.passed ? 'pass' : 'fail'}`} key={i}>
              <div><Pill tone={c.passed ? 'pass' : 'fail'}>{c.passed ? 'pass' : 'fail'}</Pill> <span className="mono small">{c.name}</span></div>
              {c.detail && <div className="small muted">verdict: {c.detail}</div>}
              {c.reasoning && <p className="reasoning">{c.reasoning}</p>}
            </div>
          ))}

          {t.rule_events.length > 0 && (
            <>
              <h3>Rule hits</h3>
              <ul className="plain">
                {t.rule_events.map((r, i) => (
                  <li key={i}><Pill tone="warn">{r.rule}</Pill> <span className="mono small">{r.tool}</span><div className="small muted">{r.message}</div></li>
                ))}
              </ul>
            </>
          )}

          {t.approvals.length > 0 && (
            <>
              <h3>Approvals requested</h3>
              <ul className="plain">
                {t.approvals.map(a => (
                  <li key={a.id}><span className="mono small">{a.action}</span> {a.amount !== null && <span className="mono small">{money(a.amount)}</span>} <Pill tone="neutral">{a.status}</Pill><div className="small muted">{a.reason}</div></li>
                ))}
              </ul>
              <p className="small"><Link to="/approvals">Approval queue</Link> {'→'} run {runId}</p>
            </>
          )}

          <h3>State diff</h3>
          {stateKeys.length === 0 ? <p className="muted small">No state changes.</p> : <Json value={t.state_diff} />}
        </aside>
      </div>
    </div>
  )
}

export default function Scenario() {
  const { id = '', sid = '' } = useParams()
  const state = useApi<ScenarioDetail>(`/api/runs/${encodeURIComponent(id)}/scenarios/${encodeURIComponent(sid)}`)
  const [idx, setIdx] = useState(0)
  return (
    <Async state={state}>
      {d => {
        const t = d.trials[Math.min(idx, d.trials.length - 1)]
        return (
          <>
            <div className="crumbs"><Link to="/">Runs</Link> / <Link to={`/runs/${encodeURIComponent(id)}`} className="mono">{id}</Link> / <span className="mono">{sid}</span></div>
            <div className="page-head">
              <div>
                <h1 className="mono h1-mono">{d.scenario_id}</h1>
                <p className="muted">{t.category} &middot; {d.trials.filter(x => x.success).length}/{d.trials.length} trials succeeded</p>
              </div>
            </div>
            <div className="tabs" role="tablist">
              {d.trials.map((x, i) => (
                <button key={i} role="tab" aria-selected={i === idx} className={`tab ${i === idx ? 'on' : ''}`} onClick={() => setIdx(i)}>
                  <span className={`dot ${x.success ? 'pass' : 'fail'}`} /> Trial {x.trial_index}
                </button>
              ))}
            </div>
            <TrialView key={idx} t={t} runId={id} />
          </>
        )
      }}
    </Async>
  )
}
