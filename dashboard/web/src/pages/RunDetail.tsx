import { Link, useParams } from 'react-router-dom'
import { useApi } from '../api'
import { Async, Bar, Empty, Stat } from '../ui'
import { dash, flag, money, ms, num, pct, pctCi, date } from '../format'
import type { Metrics } from '../types'
import type { RunDetail as Detail } from '../types'

function passHat(m: Metrics): number | undefined {
  return typeof m.k === 'number' ? (m[`pass^${m.k}`] as number | undefined) : undefined
}

function MetricRow({ name, m }: { name: string; m: Metrics }) {
  return (
    <tr>
      <td>{name}</td>
      <td className="num mono">{m.n_trials}</td>
      <td className="num mono nowrap">{pctCi(m.success_rate, m.success_ci95)}</td>
      <td className="num mono">{pct(passHat(m))}</td>
      <td className={`num mono ${m.policy_violation_rate ? 'bad' : ''}`}>{pct(m.policy_violation_rate)}</td>
      <td className="num mono">{pct(m.policy_attempt_rate)}</td>
      <td className="num mono">{pct(m.tool_error_rate)}</td>
      <td className="num mono">{ms(m.latency_p50_ms)} / {ms(m.latency_p95_ms)}</td>
      <td className="num mono">{money(m.cost_per_conversation_usd)}</td>
      <td className="num mono">{money(m.cost_per_success_usd)}</td>
    </tr>
  )
}

export default function RunDetail() {
  const { id = '' } = useParams()
  const state = useApi<Detail>(`/api/runs/${encodeURIComponent(id)}`)
  return (
    <Async state={state}>
      {d => {
        const o = d.summary?.overall ?? ({ n_trials: 0 } as Metrics)
        const r = d.run
        const cats = Object.entries(d.summary?.by_category ?? {})
        return (
          <>
            <div className="crumbs"><Link to="/">Runs</Link> / <span className="mono">{r.id}</span></div>
            <div className="page-head">
              <div>
                <h1>{r.label || r.id}</h1>
                <p className="muted">
                  {date(r.created_at)} &middot; {r.environment} &middot; {r.agent_type} &middot; <span className="mono">{r.model ?? dash}</span> &middot; prompt{' '}
                  <span className="mono">{r.prompt_version ?? dash}</span> &middot; retrieval {flag(r.retrieval)} &middot; injection defence {flag(r.injection_defense)}
                </p>
              </div>
              <div className="toolbar">
                <Link className="btn" to={`/runs/${encodeURIComponent(r.id)}/failures`}>Failure patterns</Link>
              </div>
            </div>
            {d.aborted && <p className="banner fail">Run aborted: {d.aborted}</p>}
            {o.n_trials === 0 ? (
              <Empty title="No trials in this run" />
            ) : (
              <>
                <div className="stats">
                  <Stat label="Success" value={pct(o.success_rate)} sub={`95% CI ${pctCi(o.success_rate, o.success_ci95).replace(/^[^[]*/, '')}`} />
                  <Stat label={`pass^${o.k ?? 1}`} value={pct(passHat(o))} sub="all k trials succeed" />
                  <Stat label="Policy violations" value={pct(o.policy_violation_rate)} tone={o.policy_violation_rate ? 'fail' : 'pass'} sub="harm got through" />
                  <Stat label="Policy attempts" value={pct(o.policy_attempt_rate)} sub="blocked by rules" />
                  <Stat label="Tool errors" value={pct(o.tool_error_rate)} sub={`${num(o.avg_turns)} avg turns`} />
                  <Stat label="Latency p50 / p95" value={`${ms(o.latency_p50_ms)}`} sub={`p95 ${ms(o.latency_p95_ms)}`} />
                  <Stat label="$ / conversation" value={money(o.cost_per_conversation_usd)} sub={`total ${money(o.total_agent_cost_usd)}`} />
                  <Stat label="$ / success" value={money(o.cost_per_success_usd)} sub={`${o.n_trials} trials, ${o.n_scenarios ?? dash} scenarios`} />
                </div>

                <h2>By category</h2>
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Category</th><th className="num">Trials</th><th className="num">Success (95% CI)</th><th className="num">pass^k</th>
                        <th className="num">Violations</th><th className="num">Attempts</th><th className="num">Tool err.</th>
                        <th className="num">Latency p50 / p95</th><th className="num">$/conv</th><th className="num">$/success</th>
                      </tr>
                    </thead>
                    <tbody>
                      <MetricRow name="All" m={o} />
                      {cats.map(([c, m]) => <MetricRow key={c} name={c} m={m} />)}
                    </tbody>
                  </table>
                </div>

                <h2>Scenarios</h2>
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr><th>Scenario</th><th>Category</th><th>Pass rate</th><th className="num">Successes</th><th className="num">Violations</th><th>Failed checks</th></tr>
                    </thead>
                    <tbody>
                      {d.scenarios.map(s => (
                        <tr key={s.scenario_id}>
                          <td className="mono"><Link to={`/runs/${encodeURIComponent(r.id)}/scenarios/${encodeURIComponent(s.scenario_id)}`}>{s.scenario_id}</Link></td>
                          <td>{s.category}</td>
                          <td><Bar value={s.successes / s.trials} tone={s.successes === s.trials ? 'pass' : s.successes === 0 ? 'fail' : 'warn'} /></td>
                          <td className="num mono">{s.successes}/{s.trials}</td>
                          <td className={`num mono ${s.violations ? 'bad' : ''}`}>{s.violations}</td>
                          <td className="small">{s.failed_checks.length ? s.failed_checks.join(', ') : <span className="muted">{dash}</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )
      }}
    </Async>
  )
}
