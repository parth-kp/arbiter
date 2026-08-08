import { useApi } from '../api'
import { Async, Empty, Pill } from '../ui'
import { dash, pct } from '../format'
import type { CalibrationReport } from '../types'

function isReport(r: unknown): r is CalibrationReport {
  return typeof r === 'object' && r !== null && 'criteria' in r && typeof (r as CalibrationReport).criteria === 'object'
}

export default function Calibration() {
  const state = useApi<unknown[]>('/api/calibration')
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Judge calibration</h1>
          <p className="muted">Agreement between human labels and the LLM judge. Cohen's kappa below 0.4 means the criterion is unreliable.</p>
        </div>
      </div>
      <Async state={state}>
        {raw => {
          const reports = raw.filter(isReport)
          if (reports.length === 0) {
            return (
              <Empty title="No calibration reports yet">
                Label some items on the Labelling page, then run <code>arbiter calibrate</code>. Reports are written to <code>results/calibration</code>.
              </Empty>
            )
          }
          return (
            <>
              {reports.map(r => (
                <section key={`${r.rubric}-${r.version}`} className="report">
                  <h2>{r.rubric} <span className="muted mono small">{r.version}</span></h2>
                  <p className="muted small">Judge <span className="mono">{r.judge_model}</span> &middot; {r.n_items} labelled items</p>
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr><th>Criterion</th><th className="num">n</th><th className="num">Agreement</th><th className="num">Kappa</th><th className="num">Kappa 95% CI</th><th className="num">Human pass</th><th className="num">Judge pass</th><th>Reliability</th></tr>
                      </thead>
                      <tbody>
                        {Object.entries(r.criteria).map(([c, m]) => {
                          if (!m.n) return <tr key={c}><td className="mono">{c}</td><td className="num mono">0</td><td colSpan={6} className="muted">no labelled overlap</td></tr>
                          const bad = m.kappa === null || m.kappa === undefined || m.kappa < 0.4
                          return (
                            <tr key={c} className={bad ? 'unreliable' : ''}>
                              <td className="mono">{c}</td>
                              <td className="num mono">{m.n}</td>
                              <td className="num mono">{pct(m.agreement)}</td>
                              <td className={`num mono ${bad ? 'bad' : 'good'}`}>{m.kappa == null ? dash : m.kappa.toFixed(2)}</td>
                              <td className="num mono">{m.kappa_ci95 ? `[${m.kappa_ci95[0].toFixed(2)}, ${m.kappa_ci95[1].toFixed(2)}]` : dash}</td>
                              <td className="num mono">{pct(m.human_pass_rate)}</td>
                              <td className="num mono">{pct(m.judge_pass_rate)}</td>
                              <td>{bad ? <Pill tone="fail">unreliable</Pill> : <Pill tone="pass">usable</Pill>}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </section>
              ))}
            </>
          )
        }}
      </Async>
    </>
  )
}
