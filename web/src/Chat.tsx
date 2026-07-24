import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { marked } from 'marked'

marked.use({ breaks: true, gfm: true })

const API = (import.meta.env.VITE_API_BASE as string | undefined) || ''

type CiteItem = { source: string; chapter: string; excerpt?: string }
type Msg = { role: 'user' | 'assistant'; text: string; cite?: CiteItem[] }

// 「出自《…》·章节;《…》章节」引用串的解析与剥离。
// 引用不总在行首(模型可能写在行内或裹 **/引用块),故不做行锚定,全局匹配。
const CITE_RE = /[ \t>*_—–-]*出自[^\n]*/g

function parseCiteLine(line: string): CiteItem[] {
  const body = line.replace(/^[ \t>*_—–-]*出自[：:]?\s*/, '')
  return body.split(/[;;]\s*/).map(part => {
    const p = part.trim().replace(/[*_]+$/g, '')
    if (!p) return null
    const m = p.match(/^(《[^》]+》)\s*[·．.•]?\s*(.*)$/)
    if (m) return { source: m[1], chapter: m[2].trim().replace(/[*_]+$/g, '') }
    return { source: p, chapter: '' }
  }).filter((c): c is CiteItem => !!c && !!c.source)
}

function extractCite(text: string): { text: string; parsed: CiteItem[] } {
  const parsed: CiteItem[] = []
  const cleaned = text.replace(CITE_RE, m => { parsed.push(...parseCiteLine(m)); return '' })
  return { text: cleaned, parsed }
}

function CiteCard({ item, index }: { item: CiteItem; index: number }) {
  return (
    <div className="cite">
      <div className="cite-head">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
        <span>引用出处 {index + 1}</span>
      </div>
      <div className="cite-row">
        <span className="cite-doc" aria-hidden="true">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <path d="M14 2v6h6" /><path d="M9 13h6" /><path d="M9 17h6" />
          </svg>
        </span>
        <span className="cite-txt">
          <span className="cite-src">{item.source}</span>
          {item.chapter && <span className="cite-ch">{item.chapter}</span>}
        </span>
      </div>
      {item.excerpt && <p className="cite-excerpt">“{item.excerpt}”</p>}
    </div>
  )
}

export default function Chat({ role, title, accent, suggestions }: {
  role: string; title: string; accent: string; suggestions: string[]
}) {
  const [session, setSession] = useState('')
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [showMenu, setShowMenu] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inited = useRef(false)

  useEffect(() => {
    if (inited.current) return
    inited.current = true
    fetch(`${API}/api/session`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    })
      .then(r => r.json())
      .then(d => {
        setSession(d.session_id)
        setMessages([{ role: 'assistant', text: d.welcome }])
        setShowMenu(true)
      })
      .catch(() => setError('无法连接服务,请检查网络或稍后重试。'))
  }, [role])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, progress, error])

  async function send(raw: string) {
    const text = raw.trim()
    if (!text || busy || !session) return
    setInput('')
    setError('')
    setBusy(true)
    setProgress('思考中…')
    setShowMenu(false)
    setMessages(m => [...m, { role: 'user', text }, { role: 'assistant', text: '' }])
    let reply = ''
    let rafPending = false
    // 真流式下 token 逐个到达,合并为每帧一次更新,避免高频 setState 与 markdown 重解析卡顿
    const scheduleFlush = () => {
      if (rafPending) return
      rafPending = true
      requestAnimationFrame(() => {
        rafPending = false
        setMessages(m => {
          const copy = [...m]
          copy[copy.length - 1] = { role: 'assistant', text: reply }
          return copy
        })
      })
    }
    try {
      const res = await fetch(`${API}/api/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session, text }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      const flush = (block: string) => {
        let eventName = 'message'
        let data = ''
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) eventName = line.slice(6).trim()
          else if (line.startsWith('data:')) data += line.slice(5).trim()
        }
        if (!data) return
        let payload: any
        try { payload = JSON.parse(data) } catch { return }
        if (eventName === 'tool') {
          setProgress(payload.summary || payload.name || '处理中…')
        } else if (eventName === 'delta') {
          reply += payload.text
          scheduleFlush()
        } else if (eventName === 'error') {
          setError(payload.error || '服务异常,请稍后重试。')
        } else if (eventName === 'done') {
          if (payload.reset) setShowMenu(true)
          // 定稿:无论后端是否下发结构化 cite,都剥掉正文里的「出自」原始串,保证不残留;
          // 引用统一以卡片呈现(后端 cite 优先、带原文摘录,缺失时用解析结果兜底),保证不丢失。
          let finalText = reply.replace(/\r\n/g, '\n')
          const { text: stripped, parsed } = extractCite(finalText)
          finalText = stripped.replace(/\n{3,}/g, '\n\n').replace(/\s+$/, '')
          const cite: CiteItem[] | undefined =
            (Array.isArray(payload.cite) && payload.cite.length)
              ? payload.cite as CiteItem[]
              : (parsed.length ? parsed : undefined)
          setMessages(m => {
            const copy = [...m]
            copy[copy.length - 1] = { role: 'assistant', text: finalText, cite }
            return copy
          })
        }
      }
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        // 服务端 SSE 以 \r\n 分行、\r\n\r\n 分隔事件;统一归一为 \n 再切块
        buf += decoder.decode(value, { stream: true })
        buf = buf.replace(/\r\n/g, '\n')
        let idx
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          flush(buf.slice(0, idx))
          buf = buf.slice(idx + 2)
        }
      }
      if (buf.trim()) flush(buf)
    } catch {
      setError('网络异常,请稍后重试。')
    } finally {
      setBusy(false)
      setProgress('')
    }
  }

  function reset() {
    if (!busy) void send('重新开始')
  }

  const md = (text: string, streaming = false) => {
    if (!text) return ''
    let html = marked.parse(text) as string
    if (streaming) {
      // 在最后一段末尾插入闪烁光标,提示"正在生成"
      const i = html.lastIndexOf('</p>')
      html = i >= 0
        ? html.slice(0, i) + '<span class="scursor"></span>' + html.slice(i)
        : html + '<span class="scursor"></span>'
    }
    return html
  }

  return (
    <div className="chat" style={{ '--accent': accent } as React.CSSProperties}>
      <header className="topbar">
        <Link to="/" className="back" aria-label="返回">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </Link>
        <h1>{title}</h1>
        <span className="live"><i />在线</span>
        <button className="reset" onClick={reset} disabled={busy || !session}>重新开始</button>
      </header>

      <main className="msgs">
        {!session && !error && (
          <>
            <div className="row assistant"><div className="bubble skeleton"><i /><i /><i /></div></div>
            <div className="row assistant"><div className="bubble skeleton"><i /><i /></div></div>
          </>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`row ${m.role}`}>
            {m.role === 'assistant'
              ? (<>
                {m.text
                  ? <div className="bubble md"
                      dangerouslySetInnerHTML={{ __html: md(m.text, busy && i === messages.length - 1) }} />
                  : (busy && i === messages.length - 1
                    ? <div className="bubble typing"><i /><i /><i /></div>
                    : null)}
                {m.cite && m.cite.length > 0 && (
                  <div className="cites">
                    {m.cite.map((c, k) => <CiteCard key={k} item={c} index={k} />)}
                  </div>
                )}
              </>)
              : <div className="bubble">{m.text}</div>}
          </div>
        ))}
        {progress && busy && <div className="progress">{progress}</div>}
        {error && (
          <div className="errbar">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="m21.7 18-8-14a2 2 0 0 0-3.5 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3" />
              <path d="M12 9v4" /><path d="M12 17h.01" />
            </svg>
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      {showMenu && !busy && (
        <div className="chips">
          {suggestions.map(s => (
            <button key={s} onClick={() => send(s)}>{s}</button>
          ))}
        </div>
      )}

      <footer className="inputbar">
        <textarea
          value={input}
          placeholder="请输入你的问题(500字以内)…"
          rows={1}
          maxLength={600}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void send(input)
            }
          }}
        />
        <button className="send" disabled={busy || !input.trim() || !session}
          onClick={() => send(input)}>
          发送
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m5 12 14-9-4 9 4 9-14-9Z" /><path d="M19 12H9" />
          </svg>
        </button>
      </footer>
    </div>
  )
}
