import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, post, useApi } from '../api'
import { Async, Empty, Json, Pill } from '../ui'
import { dash, money } from '../format'
import type { ApprovalRow } from '../types'

function Card({ a, onDone }: { a: ApprovalRow; onDone: () => void }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const decide = async (decision: 'approved' | 'rejected') => {
    setBusy(true)
    setErr(null)
    try {
      await post(`/api/approvals/${a.pk}`, { decision, note })
      onDone()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setErr('Already decided or no longer exists. Refreshing the queue.')
        onDone()
      } else setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const pending = a.status === 'pending'
  return (
    <article className="approval">
      <header>
        <h2 className="mono">{a.action}</h2>
        <span className="mono amount">{a.amount === null ? dash : money(a.amount)}</span>
        <Pill tone={pending ? 'warn' : a.status === 'approved' ? 'pass' : 'fail'}>{a.status}</Pill>
      </header>
      <p>{a.reason || <span className="muted">No reason given.</span>}</p>
      {a.payload && Object.keys(a.payload).length > 0 && (
        <details><summary className="small">Payload</summary><Json value={a.payload} /></details>
      )}
      <p className="small muted">
        {a.run_id && a.scenario_id ? (
          <Link className="mono" to={`/runs/${encodeURIComponent(a.run_id)}/scenarios/${encodeURIComponent(a.scenario_id)}`}>{a.run_id} / {a.scenario_id}{a.trial_index !== null ? ` #${a.trial_index}` : ''}</Link>
        ) : 'No run linked'}
        <span className="mono"> &middot; {a.approval_id}</span>
      </p>
      {pending ? (
        <div className="decide">
          <input type="text" placeholder="Optional note" value={note} onChange={e => setNote(e.target.value)} aria-label="Note" />
          <button className="btn approve" disabled={busy} onClick={() => decide('approved')}>Approve</button>
          <button className="btn reject" disabled={busy} onClick={() => decide('rejected')}>Reject</button>
        </div>
      ) : (
        <p className="small muted">Decided by {a.decided_by ?? dash}{a.decided_at ? ` at ${a.decided_at}` : ''}{a.note ? `: ${a.note}` : ''}</p>
      )}
      {err && <p className="banner fail">{err}</p>}
    </article>
  )
}

export default function Approvals() {
  const [all, setAll] = useState(false)
  const state = useApi<ApprovalRow[]>(all ? '/api/approvals' : '/api/approvals?status=pending')
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Approvals</h1>
          <p className="muted">Actions the agent asked a human to authorise before they take effect.</p>
        </div>
        <div className="toolbar">
          <label className="field inline"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} /> Show decided</label>
        </div>
      </div>
      <Async state={state}>
        {rows =>
          rows.length === 0 ? (
            <Empty title={all ? 'No approvals recorded' : 'No pending approvals'}>Requests appear here when an agent hits an approval rule.</Empty>
          ) : (
            <div className="approvals">
              {[...rows].reverse().map(a => <Card key={a.pk} a={a} onDone={state.reload} />)}
            </div>
          )
        }
      </Async>
    </>
  )
}
