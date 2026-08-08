import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useApi } from '../api'
import { Async, Empty, Json } from '../ui'
import { ms } from '../format'
import type { TraceResponse } from '../types'

export default function Trace() {
  const { id = '' } = useParams()
  const state = useApi<TraceResponse>(`/api/traces/${encodeURIComponent(id)}`)
  const [open, setOpen] = useState<number | null>(null)
  return (
    <Async state={state}>
      {t => {
        const total = Math.max(1, ...t.spans.map(s => s.offset_ms + s.duration_ms))
        return (
          <>
            <div className="crumbs">
              <Link to="/">Runs</Link> / <Link className="mono" to={`/runs/${encodeURIComponent(t.run_id)}`}>{t.run_id}</Link> /{' '}
              <Link className="mono" to={`/runs/${encodeURIComponent(t.run_id)}/scenarios/${encodeURIComponent(t.scenario_id)}`}>{t.scenario_id}</Link> / trace
            </div>
            <div className="page-head"><div><h1>Trace</h1><p className="muted mono">{t.trace_id} &middot; trial {t.trial_index} &middot; {t.spans.length} spans &middot; {ms(total)}</p></div></div>
            {t.spans.length === 0 ? <Empty title="No spans recorded" /> : (
              <div className="waterfall">
                <div className="wf-axis"><span>0</span><span>{ms(total / 2)}</span><span>{ms(total)}</span></div>
                {t.spans.map((s, i) => (
                  <div key={i}>
                    <button className={`wf-row ${open === i ? 'on' : ''}`} onClick={() => setOpen(open === i ? null : i)} title={s.attributes ? JSON.stringify(s.attributes) : undefined}>
                      <span className="wf-name mono">{s.name}</span>
                      <span className="wf-track">
                        <span className="wf-bar" style={{ left: `${(s.offset_ms / total) * 100}%`, width: `max(2px, ${(s.duration_ms / total) * 100}%)` }} />
                      </span>
                      <span className="wf-dur mono">{ms(s.duration_ms)}</span>
                    </button>
                    {open === i && <div className="wf-detail"><div className="small muted">offset {ms(s.offset_ms)}</div><Json value={s.attributes ?? {}} /></div>}
                  </div>
                ))}
              </div>
            )}
          </>
        )
      }}
    </Async>
  )
}
