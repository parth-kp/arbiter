import type { TranscriptEvent } from './types'
import { Json } from './ui'

interface Item {
  call?: TranscriptEvent
  result?: TranscriptEvent
  msg?: TranscriptEvent
}

function group(events: TranscriptEvent[]): Item[] {
  const items: Item[] = []
  const open: Item[] = []
  for (const e of events) {
    if (e.kind === 'tool_call') {
      const it = { call: e }
      items.push(it)
      open.push(it)
    } else if (e.kind === 'tool_result') {
      const idx = open.findIndex(o => o.call?.tool === e.tool)
      if (idx >= 0) open.splice(idx, 1)[0].result = e
      else items.push({ result: e })
    } else {
      items.push({ msg: e })
    }
  }
  return items
}

function Tool({ item }: { item: Item }) {
  const r = item.result
  const name = item.call?.tool ?? r?.tool ?? 'tool'
  const blocked = Boolean(r && (r.rule || r.error_kind === 'rule'))
  const failed = Boolean(r && r.ok === false && !blocked)
  const tone = blocked ? 'blocked' : failed ? 'failed' : ''
  return (
    <details className={`tool ${tone}`} open={blocked || failed}>
      <summary>
        <span className="tool-name mono">{name}</span>
        {blocked && <span className="pill warn">POLICY BLOCKED{r?.rule ? `: ${r.rule}` : ''}</span>}
        {failed && <span className="pill fail">{r?.error_kind ?? 'error'}</span>}
        {r && !blocked && !failed && <span className="pill pass">ok</span>}
        {!r && <span className="pill neutral">no result</span>}
      </summary>
      <div className="tool-body">
        {item.call && (
          <>
            <div className="tool-label">arguments</div>
            <Json value={item.call.arguments ?? {}} />
          </>
        )}
        {r && (
          <>
            <div className="tool-label">{blocked ? 'blocked by rule' : failed ? 'error' : 'result'}</div>
            <Json value={r.result ?? r.content ?? null} />
          </>
        )}
      </div>
    </details>
  )
}

export default function Transcript({ events }: { events: TranscriptEvent[] }) {
  if (!events.length) return <p className="muted">Empty transcript.</p>
  return (
    <div className="chat">
      {group(events).map((it, i) => {
        if (it.call || it.result) return <div className="row tool-row" key={i}><Tool item={it} /></div>
        const e = it.msg!
        if (e.kind === 'user' || e.kind === 'assistant') {
          return (
            <div className={`row ${e.kind}`} key={i}>
              <div className="bubble">
                <div className="who">{e.kind === 'user' ? 'User' : 'Assistant'} <span className="muted">turn {e.turn}</span></div>
                <div className="text">{e.content}</div>
              </div>
            </div>
          )
        }
        return (
          <div className="row note" key={i}>
            <div className={`note-box ${e.kind === 'error' ? 'fail' : ''}`}>{e.kind}: {e.content}</div>
          </div>
        )
      })}
    </div>
  )
}
