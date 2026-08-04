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
        <div className="tadm-stat"><em>{stats.quota.used}</em><span>累计对话</span></div>
        <div className="tadm-stat">
          <em>{stats.quota.unlimited ? '∞' : stats.quota.remaining}</em>
          <span>{stats.quota.unlimited ? '套餐不限次' : '剩余'}</span>
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

/* ---------- 机构信息维护(机构名称 + 统一服务宗旨) ---------- */
export function TenantInstitutionTab({ onChanged }: {
  info: TenantInfo | null; onChanged: () => void
}) {
  const [name, setName] = useState('')
  const [purpose, setPurpose] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api('/api/tenant/institution').then(d => {
      setName(d.name || '')
      setPurpose(d.service_purpose || '')
    }).catch(e => setErr(e.message))
  }, [])

  async function save() {
    setBusy(true); setErr(''); setMsg('')
    try {
      await api('/api/tenant/institution', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), service_purpose: purpose.trim() }),
      })
      setMsg('已保存 · 新会话即时生效')
      onChanged()
    } catch (e: any) { setErr(e.message || '保存失败') } finally { setBusy(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
      <div className="p-card">
        <h3>机构信息</h3>
        <p className="p-scope-hint">维护机构对外展示名称与管理台标题,保存后即时生效。</p>
        <div style={{ maxWidth: 560 }}>
          <label className="auth-field">
            <span>机构名称(1-40 字)</span>
            <input value={name} maxLength={40} onChange={e => setName(e.target.value)}
              placeholder="例如:启明教育培训学校" />
          </label>
        </div>
      </div>

      <div className="p-card">
        <h3>统一服务宗旨</h3>
        <p className="p-scope-hint">
          该机构所有智能体的共同服务导向,置于每个智能体系统提示词顶部,优先级最高;
          留空则仅使用各智能体自身配置。保存后新会话即时生效。
        </p>
        <textarea className="p-scope-editor" rows={5} value={purpose} maxLength={500}
          onChange={e => setPurpose(e.target.value)}
          placeholder={'例如:以学员成长为中心,诚实守信,不夸大宣传,耐心解答每一位学员与家长的问题。'} />
        <div className="p-toolbar" style={{ marginTop: 12 }}>
          <button disabled={busy} onClick={save}>{busy ? '保存中…' : '保存设置'}</button>
          {msg && <span className="p-ok">{msg}</span>}
          {err && <span className="p-err">{err}</span>}
        </div>
      </div>
    </div>
  )
}

/* ---------- 智能体设置(多智能体:新建 + 独立前台链接 + 按套餐锁配置) ---------- */
const AGENT_CAPS = [
  { key: 'lead_capture', label: '留资转线索', desc: '用户表达报名意向时采集联系方式,转线索跟进' },
  { key: 'quality_check', label: '对话质检', desc: '对该智能体的会话进行质检评分' },
]

export function TenantAgentTab({ info }: { info: TenantInfo | null }) {
  const [agents, setAgents] = useState<any[]>([])
  const [agentLimit, setAgentLimit] = useState(1)
  const [features, setFeatures] = useState<any>({})
  const [sel, setSel] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [err, setErr] = useState('')
  const feats = info?.subscription?.features || features || {}
  const canDomains = !!feats.domains
  const canCaps = !!feats.agent_caps

  const loadAgents = useCallback(() => {
    api('/api/tenant/agents').then(d => {
      setAgents(d.agents || [])
      setAgentLimit(d.agent_limit ?? 1)
      setFeatures(d.features || {})
      setSel(s => (s && (d.agents || []).some((a: any) => a.id === s))
        ? s : ((d.agents || [])[0]?.id ?? null))
    }).catch(() => {})
  }, [])
  useEffect(() => { loadAgents() }, [loadAgents])

  async function createAgent() {
    if (!newName.trim()) return
    setErr('')
    try {
      const r = await api('/api/tenant/agents', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName.trim() }),
      })
      setNewName(''); setCreating(false)
      await loadAgents()
      setSel(r.agent.id)
    } catch (e: any) { setErr(e.message || '创建失败') }
  }

  async function delAgent(a: any) {
    if (!confirm(`删除智能体「${a.name}」?其前台链接将失效。`)) return
    setErr('')
    try {
      await api(`/api/tenant/agents/${a.id}`, { method: 'DELETE' })
      loadAgents()
    } catch (e: any) { setErr(e.message || '删除失败') }
  }

  const selAgent = agents.find(a => a.id === sel)
  const overLimit = agentLimit >= 0 && agents.length >= agentLimit
  return (
    <div className="p-docgrid">
      <div className="p-kblist">
        {agents.map(a => (
          <button key={a.id} className={`p-kb ${a.id === sel ? 'on' : ''}`}
            onClick={() => setSel(a.id)}>
            <b>{a.name}</b>
            <small>独立前台对话入口</small>
            <span className="meta">
              <span className="p-mono">{a.link}</span>
              <span className="p-count">{a.domain_count || '全部'} 知识域</span>
            </span>
          </button>
        ))}
        {creating
          ? (
            <div className="p-kbform">
              <input placeholder="智能体名称(1-20字)" value={newName} maxLength={20}
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createAgent()} />
              <div className="p-kbform-btns">
                <button onClick={createAgent}>创建</button>
                <button className="ghost" onClick={() => setCreating(false)}>取消</button>
              </div>
            </div>
          )
          : (
            <button className="p-kb-new" disabled={overLimit}
              title={overLimit ? `当前套餐最多 ${agentLimit} 个智能体` : ''}
              onClick={() => setCreating(true)}>+ 新建智能体</button>
          )}
        {overLimit && (
          <p className="p-scope-hint" style={{ padding: '0 4px' }}>
            已达当前套餐上限({agentLimit} 个),升级套餐可新建更多。
          </p>
        )}
        {err && <p className="p-err" style={{ padding: '0 4px' }}>{err}</p>}
      </div>

      {selAgent
        ? <AgentConfigPanel key={selAgent.id} agent={selAgent}
            canDomains={canDomains} canCaps={canCaps}
            onDelete={agents.length > 1 ? () => delAgent(selAgent) : undefined} />
        : <div className="p-empty">暂无智能体,请先新建</div>}
    </div>
  )
}

function AgentConfigPanel({ agent, canDomains, canCaps, onDelete }: {
  agent: any; canDomains: boolean; canCaps: boolean; onDelete?: () => void
}) {
  const [cfg, setCfg] = useState<any>(null)
  const [options, setOptions] = useState<string[]>([])
  const [defaultModel, setDefaultModel] = useState('')
  const [link, setLink] = useState(agent.link)
  const [domains, setDomains] = useState<any[]>([])
  const [prompt, setPrompt] = useState('')
  const [welcome, setWelcome] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => {
    api(`/api/tenant/agents/${agent.id}/config`).then(d => {
      setCfg(d.config)
      setPrompt(d.config?.prompt_text || '')
      setWelcome(d.config?.welcome_text || '')
      setOptions(d.model_options || [])
      setDefaultModel(d.default_model || '')
      setLink(d.link || agent.link)
    }).catch(e => setErr(e.message))
    api('/api/portal/domains').then(setDomains).catch(() => {})
  }, [agent.id])

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(''), 3000) }

  async function put(patch: Record<string, unknown>) {
    setErr('')
    try {
      const r = await api(`/api/tenant/agents/${agent.id}/config`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      setCfg((c: any) => ({ ...c, ...r.config }))
      return true
    } catch (e: any) { setErr(e.message || '保存失败'); return false }
  }

  async function copyLink() {
    const url = window.location.origin + link
    try { await navigator.clipboard.writeText(url); flash('前台链接已复制') }
    catch { setErr('复制失败,请手动复制:' + url) }
  }

  if (!cfg) return <div className="p-empty">{err || '加载中…'}</div>
  const bound: number[] = cfg.domains || []
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
      <div className="p-card">
        <h3>前台链接(该智能体专属)</h3>
        <p className="p-scope-hint">访客打开此链接即与本智能体对话,配置与知识域挂载仅对该链接生效。</p>
        <div className="p-endpoint">
          <code>{link}</code>
          <button className="p-mini" onClick={copyLink}>复制链接</button>
          <a className="p-mini" href={link} target="_blank" rel="noreferrer"
            style={{ textDecoration: 'none' }}>新窗口打开</a>
        </div>
      </div>

      <div className="p-card">
        <h3>推理模型</h3>
        <p className="p-scope-hint">
          为该智能体选择对话模型;不选则跟随平台默认模型。切换即时生效,仅影响本智能体的对话生成。
        </p>
        <div className="p-modelpick">
          <select value={cfg.model || ''}
            onChange={async e => {
              if (await put({ model: e.target.value })) {
                flash(e.target.value ? `对话模型已切换为 ${e.target.value}` : '已恢复平台默认模型')
              }
            }}>
            <option value="">平台默认模型{defaultModel ? `(${defaultModel})` : ''}</option>
            {options.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          {msg && <span className="p-ok">{msg}</span>}
        </div>
      </div>

      <div className="p-card">
        <h3>能力配置{!canCaps && <span className="p-count" style={{ marginLeft: 8 }}>旗舰版功能 · 未解锁</span>}</h3>
        <p className="p-scope-hint">
          {canCaps
            ? '按智能体启用的扩展能力(留资转线索 / 对话质检),保存后即时生效。'
            : '能力开关为旗舰版功能,请先在「套餐订阅」中升级后配置。'}
        </p>
        <div className="p-caps" style={canCaps ? undefined : { opacity: .55, pointerEvents: 'none' }}>
          {AGENT_CAPS.map(c => {
            const on = !!cfg[c.key]
            return (
              <label key={c.key} className={`p-cap ${on ? 'on' : ''}`}
                onClick={async () => { if (await put({ [c.key]: !cfg[c.key] })) flash('能力配置已保存 · 即时生效') }}>
                <span className={`p-switch ${on ? 'on' : ''}`}><i /></span>
                <span className="p-cap-tx"><b>{c.label}</b><small>{c.desc}</small></span>
              </label>
            )
          })}
        </div>
      </div>

      <div className="p-card">
        <h3>知识域对接{!canDomains && <span className="p-count" style={{ marginLeft: 8 }}>标准版功能 · 未解锁</span>}</h3>
        <p className="p-scope-hint">
          {canDomains
            ? <>勾选本智能体可引用的知识域。<b>未勾选知识域的内容不参与检索、推荐与计算</b>;
              不勾选任何项 = 挂载本租户全部知识域;勾选变更立即保存并生效。</>
            : '知识域对接为标准版功能,请先在「套餐订阅」中升级。当前默认挂载全部知识域。'}
        </p>
        <div className="p-checks" style={canDomains ? undefined : { opacity: .55, pointerEvents: 'none' }}>
          {domains.map(d => (
            <label key={d.id} className={bound.includes(d.id) ? 'on' : ''}>
              <input type="checkbox" checked={bound.includes(d.id)}
                onChange={async () => {
                  const next = bound.includes(d.id)
                    ? bound.filter(x => x !== d.id) : [...bound, d.id]
                  if (await put({ domains: next })) flash('知识域对接已保存 · 即时生效')
                }} />
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
          <button onClick={async () => { if (await put({ prompt_text: prompt })) flash('系统提示词已保存 · 新会话即时生效') }}>保存提示词</button>
          {msg && <span className="p-ok">{msg}</span>}
        </div>
      </div>

      <div className="p-card">
        <h3>欢迎语</h3>
        <p className="p-scope-hint">新会话第一条消息;留空则使用平台默认欢迎语。保存后新会话即时生效。</p>
        <textarea className="p-scope-editor" rows={9} value={welcome} maxLength={800}
          onChange={e => setWelcome(e.target.value)} />
        <div className="p-toolbar" style={{ marginTop: 12 }}>
          <button onClick={async () => { if (await put({ welcome_text: welcome })) flash('欢迎语已保存 · 新会话即时生效') }}>保存欢迎语</button>
          {err && <span className="p-err">{err}</span>}
        </div>
      </div>

      {onDelete && (
        <div className="p-card" style={{ borderColor: 'rgba(185,28,28,.3)' }}>
          <h3 style={{ color: 'var(--bad)' }}>删除智能体</h3>
          <p className="p-scope-hint">删除后该智能体的前台链接失效,历史会话记录保留。</p>
          <div className="p-toolbar">
            <button className="p-mini danger" onClick={onDelete}>删除「{agent.name}」</button>
          </div>
        </div>
      )}
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
              <ul className="plan-points">
                {(p.features?.highlights || []).map((h: string, i: number) => (
                  <li key={i}>{h}</li>
                ))}
              </ul>
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
