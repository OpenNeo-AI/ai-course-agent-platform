/* 租户工作台功能模块(由 Portal 统一工作台按身份装配):
   课程资料 / 对话记录(脱敏+时间筛选) / 用量统计 / 套餐订阅。
   端点统一走 /api/portal/*(后端按身份自动收敛到本租户)。
   /admin 旧入口重定向至 /portal。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { api } from './api'
import PaymentModal from './PaymentModal'

export type Doc = { id: number; filename: string; title: string; status: string; chunks: number;
  entities: number; uploaded_at: string; kb_id: number }
export type TSession = { id: string; created_at: string; updated_at: string; msgs: number }
export type TenantInfo = { tenant: { id: number; slug: string; name: string }; subscription: any;
  quota: any; features: any; documents: number; bot_url: string }

export default function TenantAdmin() {
  return <Navigate to="/portal" replace />
}

/* ---------- 课程资料管理(标准版起含;未开通显示开通引导) ---------- */
export function TenantDocsTab({ info, onChanged }: { info: TenantInfo | null; onChanged: () => void }) {
  const [docs, setDocs] = useState<Doc[]>([])
  const [kbId, setKbId] = useState<number>(0)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    api('/api/portal/kbs').then(ks => { if (ks.length) setKbId(ks[0].id) }).catch(() => {})
    api('/api/portal/documents').then(setDocs).catch(() => {})
  }, [])
  useEffect(load, [load])

  const active = info?.subscription?.status === 'active'
  if (info && !active) {
    return (
      <div className="tadm-lock">
        <h3>🔒 服务未开通</h3>
        <p>注册后需选购套餐并完成支付,即可上传课程资料并启用 AI 课程顾问。</p>
        <a href="#sub" onClick={e => { e.preventDefault(); window.dispatchEvent(new CustomEvent('opc-goto-tab', { detail: 'sub' })) }}>
          前往「套餐订阅」开通 →</a>
      </div>
    )
  }

  async function upload(f: File) {
    if (!kbId) { setErr('尚未创建知识库,请先在「知识域」中创建'); return }
    setBusy(true); setErr(''); setMsg('')
    try {
      const fd = new FormData()
      fd.append('file', f)
      fd.append('kb_id', String(kbId))
      const token = localStorage.getItem('opc_portal_token') || ''
      const res = await fetch('/api/portal/documents', {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd,
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || `上传失败(${res.status})`)
      const s = d.stats || {}
      const ex = s.extract || {}
      setMsg(`上传成功:切块 ${s.chunks ?? 0} · 实体 ${ex.entities ?? 0} · 规则 ${ex.rules ?? 0},Bot 已可基于新资料回答`)
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
      await api(`/api/portal/documents/${id}`, { method: 'DELETE' })
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
export function TenantSessionsTab() {
  const [list, setList] = useState<TSession[]>([])
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [sel, setSel] = useState<string>('')
  const [msgs, setMsgs] = useState<any[]>([])

  const load = useCallback(() => {
    const q = new URLSearchParams()
    if (from) q.set('date_from', from)
    if (to) q.set('date_to', to)
    api('/api/portal/sessions?' + q.toString()).then(setList).catch(() => {})
  }, [from, to])
  useEffect(load, [load])

  useEffect(() => {
    if (!sel) return
    api(`/api/portal/sessions/${sel}/messages`).then(setMsgs).catch(() => {})
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
export function TenantStatsTab() {
  const [stats, setStats] = useState<any>(null)
  useEffect(() => { api('/api/tenant/stats').then(setStats).catch(() => {}) }, [])
  if (!stats) return <section className="tadm-card">加载中…</section>
  const max = Math.max(1, ...stats.trend.map((t: any) => t.count))
  return (
    <section className="tadm-card">
      <h3>用量统计</h3>
      <div className="tadm-stat-row">
        <div className="tadm-stat"><em>{stats.chats}</em><span>总对话次数</span></div>
        <div className="tadm-stat"><em>{stats.active_users}</em><span>活跃用户量(会话)</span></div>
        <div className="tadm-stat"><em>{stats.quota.used}</em><span>本月对话</span></div>
        <div className="tadm-stat">
          <em>{stats.quota.unlimited ? '∞' : stats.quota.remaining}</em>
          <span>{stats.quota.unlimited ? '套餐不限次' : '本月剩余'}</span>
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

/* ---------- 智能体设置(免费版即可用:欢迎语/留资开关/模型) ---------- */
export function TenantAgentTab() {
  const [cfg, setCfg] = useState<any>(null)
  const [options, setOptions] = useState<string[]>([])
  const [defaultModel, setDefaultModel] = useState('')
  const [botUrl, setBotUrl] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api('/api/tenant/bot-config').then(d => {
      setCfg(d.config)
      setOptions(d.model_options || [])
      setDefaultModel(d.default_model || '')
      setBotUrl(d.bot_url || '')
    }).catch(e => setErr(e.message))
  }, [])

  async function save() {
    setBusy(true); setErr(''); setMsg('')
    try {
      await api('/api/tenant/bot-config', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      })
      setMsg('已保存,新的会话立即生效')
    } catch (e: any) { setErr(e.message || '保存失败') } finally { setBusy(false) }
  }

  if (!cfg) return <section className="tadm-card">{err || '加载中…'}</section>
  return (
    <section className="tadm-card">
      <h3>智能体设置</h3>
      <label className="auth-field" style={{ maxWidth: 640 }}>
        <span>Bot 欢迎语(留空则使用平台默认欢迎语)</span>
        <textarea value={cfg.welcome_text} rows={5} maxLength={800}
          onChange={e => setCfg({ ...cfg, welcome_text: e.target.value })}
          placeholder={'例如:你好!我是启明教育的 AI 课程顾问,可以解答课程安排、费用与推荐班型。'}
          style={{ width: '100%', padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 10, fontSize: 13.5, lineHeight: 1.7, resize: 'vertical' }} />
      </label>
      <label className="auth-field" style={{ maxWidth: 640 }}>
        <span>推理模型(留空使用平台默认{defaultModel ? `:${defaultModel}` : ''})</span>
        <select value={cfg.model || ''}
          onChange={e => setCfg({ ...cfg, model: e.target.value })}
          style={{ width: '100%', padding: '9px 12px', border: '1px solid var(--line)', borderRadius: 10, fontSize: 13.5 }}>
          <option value="">平台默认</option>
          {options.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      </label>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, marginBottom: 14 }}>
        <input type="checkbox" checked={!!cfg.lead_capture}
          onChange={e => setCfg({ ...cfg, lead_capture: e.target.checked })} />
        开启留资转线索(用户表达报名意向时采集联系方式)
      </label>
      {msg && <div className="tadm-ok" style={{ marginBottom: 10 }}>{msg}</div>}
      {err && <div className="auth-error" style={{ marginBottom: 10 }}>{err}</div>}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <button className="plan-cta" style={{ width: 'auto', padding: '9px 22px' }}
          disabled={busy} onClick={save}>{busy ? '保存中…' : '保存设置'}</button>
        {botUrl && <a className="tadm-botlink" style={{ display: 'inline-block', textDecoration: 'none' }}
          href={botUrl} target="_blank" rel="noreferrer">打开 Bot 对话验证 ↗</a>}
      </div>
    </section>
  )
}

/* ---------- 套餐订阅(开通/升级 + 订单记录) ---------- */
export function TenantSubTab({ info, onChanged }: { info: TenantInfo | null; onChanged: () => void }) {
  const [orders, setOrders] = useState<any[]>([])
  const [plans, setPlans] = useState<any[]>([])
  const [pay, setPay] = useState<any>(null)
  useEffect(() => {
    api('/api/billing/orders').then(d => setOrders(d.orders || [])).catch(() => {})
    api('/api/plans').then(d => setPlans(d.plans || [])).catch(() => {})
  }, [])
  const sub = info?.subscription
  const active = sub?.status === 'active'
  return (
    <section className="tadm-card">
      <h3>当前订阅</h3>
      <div className="tadm-sub">
        <div>
          <b className="tadm-plan-name">
            {sub?.plan_name || '—'}
            <span className={`plan-pill ${active ? 'pro' : ''}`} style={{ marginLeft: 10 }}>
              {active ? '已开通' : '待支付开通'}
            </span>
          </b>
          <small>{sub?.plan_code === 'flagship'
            ? '全部功能:知识域智能体 + 本体图谱 + 对话记录 + 线索转化 + 运营分析'
            : '知识域智能体:知识域与资料管理 + RAG 问答 + 班型推荐'}</small>
        </div>
      </div>
      <div className="pricing-cards" style={{ margin: '16px 0 6px' }}>
        {plans.map(p => {
          const current = sub?.plan_code === p.code
          return (
            <div key={p.code} className={`plan-card${p.code === 'flagship' ? ' pro' : ''}`}
              style={{ width: 'min(300px, 100%)' }}>
              {p.code === 'flagship' && <span className="plan-flag">全功能</span>}
              {current && <span className="plan-flag" style={{ background: 'var(--ok)' }}>当前</span>}
              <h2>{p.name}</h2>
              <div className="plan-price"><em>¥{p.price_monthly}</em><span>/月</span></div>
              <p className="plan-desc">{p.features?.desc}</p>
              <button className="plan-cta" disabled={current || p.code === 'free'}
                onClick={() => setPay(p)}>
                {current ? '当前套餐' : p.code === 'free' ? '注册时自动开通' : '升级开通'}
              </button>
            </div>
          )
        })}
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
        <PaymentModal plan={{ code: pay.code, name: pay.name, price_monthly: pay.price_monthly }}
          onClose={() => setPay(null)}
          onDone={() => { setPay(null); onChanged(); window.location.reload() }} />
      )}
    </section>
  )
}
