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

/* ---------- 智能体设置(与平台 AgentsTab 同构:模型/能力/知识域对接/提示词) ---------- */
const AGENT_CAPS = [
  { key: 'lead_capture', label: '留资转线索', desc: '用户表达报名意向时采集联系方式,转线索跟进' },
  { key: 'quality_check', label: '对话质检', desc: '对该智能体的会话进行质检评分' },
]

export function TenantAgentTab({ info }: { info: TenantInfo | null }) {
  const [cfg, setCfg] = useState<any>(null)
  const [options, setOptions] = useState<string[]>([])
  const [defaultModel, setDefaultModel] = useState('')
  const [botUrl, setBotUrl] = useState('')
  const [domains, setDomains] = useState<any[]>([])
  const [prompt, setPrompt] = useState('')
  const [welcome, setWelcome] = useState('')
  const [msg, setMsg] = useState('')

  const loadAll = useCallback(() => {
    api('/api/tenant/bot-config').then(d => {
      setCfg(d.config)
      setPrompt(d.config?.prompt_text || '')
      setWelcome(d.config?.welcome_text || '')
      setOptions(d.model_options || [])
      setDefaultModel(d.default_model || '')
      setBotUrl(d.bot_url || '')
    }).catch(() => {})
    api('/api/portal/domains').then(setDomains).catch(() => {})
  }, [])
  useEffect(() => { loadAll() }, [loadAll])

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(''), 3000) }

  async function put(patch: Record<string, unknown>) {
    const r = await api('/api/tenant/bot-config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    setCfg((c: any) => ({ ...c, ...r.config }))
    return r.config
  }

  async function setModel(model: string) {
    await put({ model })
    flash(model ? `对话模型已切换为 ${model}` : '已恢复平台默认模型')
  }
  async function toggleCap(key: string) {
    await put({ [key]: !cfg[key] })
    flash('能力配置已保存 · 即时生效')
  }
  async function toggleDomain(id: number) {
    const cur: number[] = cfg.domains || []
    const next = cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]
    await put({ domains: next })
    flash('知识域对接已保存 · 即时生效')
  }
  async function savePrompt() {
    await put({ prompt_text: prompt })
    flash('系统提示词已保存 · 新会话即时生效')
  }
  async function saveWelcome() {
    await put({ welcome_text: welcome })
    flash('欢迎语已保存 · 新会话即时生效')
  }

  if (!cfg) return <div className="p-empty">加载中…</div>
  const bound: number[] = cfg.domains || []
  return (
    <div className="p-docgrid">
      <div className="p-kblist">
        <div className="p-kb on">
          <b>{info?.tenant?.name || '本机构'} · AI 课程顾问</b>
          <small>租户专属 Bot,作用域限本租户知识域</small>
          <span className="meta">
            <span className="p-mono">{botUrl || '/b/…'}</span>
            <span className="p-count">{bound.length || domains.length} 知识域</span>
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
        <div className="p-card">
          <h3>推理模型</h3>
          <p className="p-scope-hint">
            为该智能体选择对话模型;不选则跟随平台默认模型。切换即时生效,仅影响本智能体的对话生成。
          </p>
          <div className="p-modelpick">
            <select value={cfg.model || ''} onChange={e => setModel(e.target.value)}>
              <option value="">平台默认模型{defaultModel ? `(${defaultModel})` : ''}</option>
              {options.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            {msg && <span className="p-ok">{msg}</span>}
          </div>
        </div>

        <div className="p-card">
          <h3>能力配置</h3>
          <p className="p-scope-hint">按智能体启用的扩展能力(留资转线索 / 对话质检),保存后即时生效。</p>
          <div className="p-caps">
            {AGENT_CAPS.map(c => {
              const on = !!cfg[c.key]
              return (
                <label key={c.key} className={`p-cap ${on ? 'on' : ''}`}
                  onClick={() => toggleCap(c.key)}>
                  <span className={`p-switch ${on ? 'on' : ''}`}><i /></span>
                  <span className="p-cap-tx"><b>{c.label}</b><small>{c.desc}</small></span>
                </label>
              )
            })}
          </div>
        </div>

        <div className="p-card">
          <h3>知识域对接</h3>
          <p className="p-scope-hint">
            勾选本 Bot 可引用的知识域。<b>未勾选知识域的内容不参与检索、推荐与计算</b>;
            不勾选任何项 = 挂载本租户全部知识域;勾选变更立即保存并生效。
          </p>
          <div className="p-checks">
            {domains.map(d => (
              <label key={d.id} className={bound.includes(d.id) ? 'on' : ''}>
                <input type="checkbox" checked={bound.includes(d.id)}
                  onChange={() => toggleDomain(d.id)} />
                <span><b>{d.name}</b><small>{d.description || d.code}</small></span>
              </label>
            ))}
            {!domains.length && <div className="p-empty">暂无知识域,请先在「知识域」中创建并上传资料</div>}
          </div>
        </div>

        <div className="p-card">
          <h3>系统提示词</h3>
          <p className="p-scope-hint">
            定义该智能体的身份、服务流程与回答风格;留空则使用平台默认模板(角色设定与红线约束)。保存后新会话即时生效。
          </p>
          <textarea className="p-scope-editor" rows={16} value={prompt} maxLength={4000}
            onChange={e => setPrompt(e.target.value)} />
          <div className="p-toolbar" style={{ marginTop: 12 }}>
            <button onClick={savePrompt}>保存提示词</button>
            {msg && <span className="p-ok">{msg}</span>}
          </div>
        </div>

        <div className="p-card">
          <h3>欢迎语</h3>
          <p className="p-scope-hint">新会话第一条消息;留空则使用平台默认欢迎语。保存后新会话即时生效。</p>
          <textarea className="p-scope-editor" rows={9} value={welcome} maxLength={800}
            onChange={e => setWelcome(e.target.value)} />
          <div className="p-toolbar" style={{ marginTop: 12 }}>
            <button onClick={saveWelcome}>保存欢迎语</button>
          </div>
        </div>
      </div>
    </div>
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
              {current
                ? <span className="plan-flag" style={{ background: 'var(--ok)' }}>当前套餐</span>
                : p.code === 'flagship' && <span className="plan-flag">全功能</span>}
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
