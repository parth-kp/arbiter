import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { post, useApi } from '../api'
import { Async, Bar, Empty } from '../ui'
import type { LabelsResponse } from '../types'

const VERDICTS = [['pass', 'Pass'], ['fail', 'Fail'], ['na', 'N/A']] as const

export default function Label() {
  const state = useApi<LabelsResponse>('/api/labels/items')
  const [labels, setLabels] = useState<Record<string, Record<string, string>>>({})
  const [i, setI] = useState(0)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (state.data) setLabels(state.data.labels)
  }, [state.data])

  const data = state.data
  const items = data?.items ?? []
  const criteria = data?.rubric.criteria ?? []

  const complete = useCallback(
    (id: string) => criteria.length > 0 && criteria.every(c => labels[id]?.[c.id]),
    [criteria, labels],
  )
  const done = useMemo(() => items.filter(it => complete(it.item_id)).length, [items, complete])

  const go = useCallback((n: number) => setI(Math.max(0, Math.min(items.length - 1, n))), [items.length])
  const nextUnlabelled = useCallback(() => {
    for (let step = 1; step <= items.length; step++) {
      const j = (i + step) % items.length
      if (!complete(items[j].item_id)) return setI(j)
    }
  }, [items, i, complete])

  const label = async (itemId: string, criterion: string, verdict: string) => {
    const prev = labels[itemId]?.[criterion]
    setLabels(l => ({ ...l, [itemId]: { ...l[itemId], [criterion]: verdict } }))
    setErr(null)
    try {
      await post('/api/labels', { item_id: itemId, criterion, verdict })
    } catch (e) {
      setLabels(l => {
        const row = { ...l[itemId] }
        if (prev) row[criterion] = prev
        else delete row[criterion]
        return { ...l, [itemId]: row }
      })
      setErr(`Could not save label: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || e.metaKey || e.ctrlKey) return
      if (e.key === 'j') go(i + 1)
      else if (e.key === 'k') go(i - 1)
      else if (e.key === 'n') nextUnlabelled()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, i, nextUnlabelled])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Labelling</h1>
          <p className="muted">Label transcripts by hand to measure how far the LLM judge can be trusted.</p>
        </div>
      </div>
      <Async state={state}>
        {() => {
          if (items.length === 0) {
            return (
              <Empty title="Nothing to label yet">
                Sample transcripts with <code>arbiter label sample</code>; they will appear here.
              </Empty>
            )
          }
          const it = items[Math.min(i, items.length - 1)]
          const row = labels[it.item_id] ?? {}
          return (
            <>
              {err && <p className="banner fail">{err}</p>}
              <div className="progress">
                <Bar value={done / items.length} tone="pass" />
                <span className="mono small">{done} / {items.length} fully labelled</span>
              </div>
              <div className="toolbar nav-row">
                <button className="btn" onClick={() => go(i - 1)} disabled={i === 0}>{'←'} Prev <kbd>k</kbd></button>
                <span className="mono small">Item {i + 1} of {items.length}</span>
                <button className="btn" onClick={() => go(i + 1)} disabled={i >= items.length - 1}>Next {'→'} <kbd>j</kbd></button>
                <button className="btn" onClick={nextUnlabelled} disabled={done === items.length}>Next unlabelled <kbd>n</kbd></button>
              </div>
              <div className="split label-split">
                <section>
                  <div className="item-meta small">
                    <Link className="mono" to={`/runs/${encodeURIComponent(it.run_id)}/scenarios/${encodeURIComponent(it.scenario_id)}`}>{it.scenario_id}</Link>
                    <span className="muted"> &middot; {it.category} &middot; trial {it.trial_index} &middot; {it.environment}</span>
                    {complete(it.item_id) && <span className="pill pass">labelled</span>}
                  </div>
                  <pre className="plain-transcript">
                    {it.transcript.split('\n').map((l, n) => {
                      const cls = l.startsWith('USER:') ? 'u' : l.startsWith('ASSISTANT:') ? 'a' : l.startsWith('[tool') ? 't' : ''
                      return <span className={`ln ${cls}`} key={n}>{l + '\n'}</span>
                    })}
                  </pre>
                </section>
                <aside className="criteria">
                  <h3>{data!.rubric.name} <span className="muted mono small">{data!.rubric.version}</span></h3>
                  {criteria.map(c => (
                    <div className={`criterion ${row[c.id] ? 'done' : ''}`} key={c.id}>
                      <div className="mono small cid">{c.id}</div>
                      <p className="q">{c.question}</p>
                      <dl className="defs">
                        <dt className="pass">Pass</dt><dd>{c.passes_when}</dd>
                        <dt className="fail">Fail</dt><dd>{c.fails_when}</dd>
                        {c.not_applicable_when && <><dt className="na">N/A</dt><dd>{c.not_applicable_when}</dd></>}
                      </dl>
                      <div className="verdicts" role="group" aria-label={`Verdict for ${c.id}`}>
                        {VERDICTS.filter(([v]) => v !== 'na' || c.not_applicable_when).map(([v, text]) => (
                          <button key={v} className={`vbtn ${v} ${row[c.id] === v ? 'on' : ''}`} aria-pressed={row[c.id] === v} onClick={() => label(it.item_id, c.id, v)}>
                            {text}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </aside>
              </div>
            </>
          )
        }}
      </Async>
    </>
  )
}
