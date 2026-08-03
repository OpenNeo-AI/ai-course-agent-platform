/* 租户管理后台 /admin:课程资料管理(专业版)、对话记录(脱敏+时间筛选)、
   用量统计、套餐订阅。平台超管访问时重定向 /portal。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, clearAuth, currentUser } from './api'
import PaymentModal from './PaymentModal'

type Doc = { id: number; filename: string; title: string; status: string; chunks: number;
  entities: number; uploaded_at: string }
type Session = { id: string; created_at: string; updated_at: string; msgs: number }
type Info = { tenant: { id: number; slug: string; name: string }; subscription: any;
  quota: any; features: any; documents: number; bot_url: string }

const TABS = [
  { key: 'docs', label: '课程资料' },
  { key: 'sessions', label: '对话记录' },
  { key: 'stats', label: '用量统计' },
  { key: 'subscription', label: '套餐订阅' },
] as const

export default function TenantAdmin() {
  const nav = useNavigate()
  const me = currentUser()
  const [tab, setTab] = useState<string>('docs')
  const [info, setInfo] = useState<Info | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!me || !me.tenant_id) { nav('/login'); return }
    if (me.role === 'superadmin') { nav('/portal'); return }
    api('/api/tenant/info').then(setInfo).catch(e => setErr(String(e.message)))
  }, [])

  const refresh = useCallback(() => {
    api('/api/tenant/info').then(setInfo).catch(() => {})
  }, [])

  if (!me || !me.tenant_id) return null
  return (
    <div className="tadm">
      <aside className="tadm-side">
        <div className="tadm-brand">
          <img src="/logo.png" alt="" />
          <div><b>AI 教育顾问</b><small>SaaS 管理后台</small></div>
        </div>
        <nav>
          {TABS.map(t => (
            <button key={t.key} className={tab === t.key ? 'on' : ''}
              onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </nav>
        <div className="tadm-side-foot">
          {info && <Link className="tadm-botlink" to={info.bot_url}>打开 Bot 对话 ↗</Link>}
          <button className="tadm-logout" onClick={() => { clearAuth(); nav('/') }}>退出登录</button>
        </div>
      </aside>

      <main className="tadm-main">
        <header className="tadm-head">
          <h1>{info?.tenant?.name || '加载中…'}</h1>
          {info && (
            <span className={`plan-pill ${info.subscription?.plan_code}`}>
              {info.subscription?.plan_name}
              {!info.quota?.unlimited && ` · 本月剩余 ${info.quota?.remaining} 次`}
            </span>
          )}
        </header>
        {err && <div className="auth-error">{err}</div>}
        {tab === 'docs' && <DocsTab info={info} onChanged={refresh} />}
        {tab === 'sessions' && <SessionsTab />}
        {tab === 'stats' && <StatsTab />}
        {tab === 'subscription' && <SubTab info={info} onChanged={refresh} />}
      </main>
    </div>
  )
}

/* ---------- 课程资料管理 ---------- */
function DocsTab({ info, onChanged }: { info: Info | null; onChanged: () => void }) {
  const [docs, setDocs] = useState<Doc[]>([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    api('/api/tenant/documents').then(setDocs).catch(() => {})
  }, [])
  useEffect(load, [load])

  if (info && !info.features?.rag_manage) {
    return (
      <div className="tadm-lock">
        <h3>🔒 课程资料管理为专业版功能</h3>
        <p>升级专业版后可上传 PDF 课程手册,系统自动解析并向量化,Bot 立即可基于新资料回答。</p>
        <Link to="/pricing">查看套餐并升级 →</Link>
      </div>
    )
  }

  async function upload(f: File) {
    setBusy(true); setErr(''); setMsg('')
    try {
      const fd = new FormData()
      fd.append('file', f)
      const token = localStorage.getItem('opc_portal_token') || ''
      const res = await fetch('/api/tenant/documents', {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd,
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || `上传失败(${res.status})`)
      const s = d.stats || {}
      setMsg(`上传成功:切块 ${s.chunks ?? 0} · 实体 ${s.entities ?? 0} · 规则 ${s.rules ?? 0},Bot 已可基于新资料回答`)
      load(); onChanged()
    } catch (e: any) {
      setErr(e.message || '上传失败')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function del(id: number) {
    if (!confirm('删除该文档?其知识块与索引将同步清理。')) return
    try {
      await api(`/api/tenant/documents/${id}`, { method: 'DELETE' })
      load(); onChanged()
    } catch (e: any) { setErr(e.message) }
  }

  return (
    <section className="tadm-card">
      <div className="tadm-docs-head">
        <h3>已挂载知识库文档({docs.length})</h3>
        <label className="tadm-upload">
          <input ref={fileRef} type="file" accept=".pdf,.txt,.docx,.doc" hidden
            onChange={e => { const f = e.target.files?.[0]; if (f) upload(f) }} />
          <button className="plan-cta" disabled={busy}
            onClick={() => fileRef.current?.click()}>
            {busy ? '解析向量化中…' : '上传课程手册(PDF)'}
          </button>
        </label>
      </div>
      {msg && <div className="tadm-ok">{msg}</div>}
      {err && <div className="auth-error">{err}</div>}
      <table className="tadm-table">
        <thead><tr><th>文档</th><th>状态</th><th>知识块</th><th>实体</th><th>上传时间</th><th /></tr></thead>
        <tbody>
          {docs.map(d => (
            <tr key={d.id}>
              <td><b>{d.title || d.filename}</b><small>{d.filename}</small></td>
              <td><span className={`st-${d.status}`}>{d.status}</span></td>
              <td>{d.chunks}</td><td>{d.entities}</td>
              <td>{d.uploaded_at}</td>
              <td><button className="tadm-del" onClick={() => del(d.id)}>删除</button></td>
            </tr>
          ))}
          {!docs.length && <tr><td colSpan={6} className="tadm-empty">暂无文档,上传课程手册后 Bot 即可基于资料回答</td></tr>}
        </tbody>
      </table>
    </section>
  )
}

/* ---------- 对话记录(脱敏 + 时间筛选) ---------- */
function SessionsTab() {
  const [list, setList] = useState<Session[]>([])
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [sel, setSel] = useState<string>('')
  const [msgs, setMsgs] = useState<any[]>([])

  const load = useCallback(() => {
    const q = new URLSearchParams()
    if (from) q.set('date_from', from)
    if (to) q.set('date_to', to)
    api('/api/tenant/sessions?' + q.toString()).then(setList).catch(() => {})
  }, [from, to])
  useEffect(load, [load])

  useEffect(() => {
    if (!sel) return
    api(`/api/tenant/sessions/${sel}/messages`).then(setMsgs).catch(() => {})
  }, [sel])

  return (
    <section className="tadm-card">
      <div className="tadm-filter">
        <h3>对话记录(内容已脱敏)</h3>
        <div className="tadm-range">
          <input type="date" value={from} onChange={e => setFrom(e.target.value)} />
          <span>至</span>
          <input type="date" value={to} onChange={e => setTo(e.target.value)} />
          <button onClick={() => { setFrom(''); setTo('') }}>清除</button>
        </div>
      </div>
      <div className="tadm-split">
        <div className="tadm-sess-list">
          {list.map(s => (
            <button key={s.id} className={sel === s.id ? 'on' : ''} onClick={() => setSel(s.id)}>
              <b>{s.id}</b>
              <small>{s.msgs} 条消息 · {s.updated_at}</small>
            </button>
          ))}
          {!list.length && <div className="tadm-empty">该时间范围内暂无对话</div>}
        </div>
        <div className="tadm-msgs">
          {!sel && <div className="tadm-empty">选择左侧会话查看消息</div>}
          {msgs.map((m, i) => (
            <div key={i} className={`tadm-msg ${m.role}`}>
              <span className="tadm-msg-role">{m.role === 'user' ? '用户' : '顾问'}</span>
              <p>{m.content}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ---------- 用量统计 ---------- */
function StatsTab() {
  const [stats, setStats] = useState<any>(null)
  useEffect(() => { api('/api/tenant/stats').then(setStats).catch(() => {}) }, [])
  if (!stats) return <section className="tadm-card">加载中…</section>
  const max = Math.max(1, ...stats.trend.map((t: any) => t.count))
  return (
    <section className="tadm-card">
      <h3>平台用量</h3>
      <div className="tadm-stat-row">
        <div className="tadm-stat"><em>{stats.chats}</em><span>总对话次数</span></div>
        <div className="tadm-stat"><em>{stats.active_users}</em><span>活跃用户量(会话)</span></div>
        <div className="tadm-stat"><em>{stats.quota.used}</em><span>本月已用</span></div>
        <div className="tadm-stat">
          <em>{stats.quota.unlimited ? '∞' : stats.quota.remaining}</em>
          <span>{stats.quota.unlimited ? '专业版不限次' : '本月剩余'}</span>
        </div>
      </div>
      <h4>近 14 日会话趋势</h4>
      <div className="tadm-trend">
        {stats.trend.map((t: any) => (
          <div key={t.date} className="tadm-trend-col" title={`${t.date}:${t.count}`}>
            <i style={{ height: `${(t.count / max) * 100}%` }} />
            <small>{t.date.slice(5)}</small>
          </div>
        ))}
      </div>
    </section>
  )
}

/* ---------- 套餐订阅 ---------- */
function SubTab({ info, onChanged }: { info: Info | null; onChanged: () => void }) {
  const [orders, setOrders] = useState<any[]>([])
  const [pay, setPay] = useState(false)
  useEffect(() => { api('/api/billing/orders').then(d => setOrders(d.orders || [])).catch(() => {}) }, [])
  const q = info?.quota
  const pct = q && !q.unlimited && q.limit > 0 ? Math.min(100, (q.used / q.limit) * 100) : 0
  return (
    <section className="tadm-card">
      <h3>当前订阅</h3>
      <div className="tadm-sub">
        <div>
          <b className="tadm-plan-name">{info?.subscription?.plan_name || '—'}</b>
          <small>{info?.subscription?.plan_code === 'pro'
            ? '无限对话 · 知识库管理 · 数据看板'
            : '每月 50 次对话'}</small>
        </div>
        {q && !q.unlimited && (
          <div className="tadm-progress">
            <div className="tadm-progress-bar"><i style={{ width: `${pct}%` }} /></div>
            <small>本月 {q.used}/{q.limit} 次</small>
          </div>
        )}
        {info?.subscription?.plan_code !== 'pro' && (
          <button className="plan-cta" style={{ width: 'auto', padding: '9px 22px' }}
            onClick={() => setPay(true)}>升级专业版 ¥99/月</button>
        )}
      </div>
      <h4>订单记录</h4>
      <table className="tadm-table">
        <thead><tr><th>订单号</th><th>套餐</th><th>渠道</th><th>金额</th><th>状态</th><th>支付时间</th></tr></thead>
        <tbody>
          {orders.map(o => (
            <tr key={o.id}>
              <td>{o.id}</td><td>{o.plan_code}</td><td>{o.channel}</td>
              <td>¥{Number(o.amount).toFixed(2)}</td>
              <td><span className={`st-${o.status === 'paid' ? 'ingested' : 'failed'}`}>
                {o.status === 'paid' ? '已支付' : o.status === 'pending' ? '待支付' : '失败'}</span></td>
              <td>{o.paid_at || '—'}</td>
            </tr>
          ))}
          {!orders.length && <tr><td colSpan={6} className="tadm-empty">暂无订单</td></tr>}
        </tbody>
      </table>
      {pay && (
        <PaymentModal plan={{ code: 'pro', name: '专业版', price_monthly: 99 }}
          onClose={() => setPay(false)}
          onDone={() => { setPay(false); onChanged() }} />
      )}
    </section>
  )
}
