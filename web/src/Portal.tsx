import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import OntologyTab from './OntologyTab'

import { api, clearAuth, TOKEN_KEY } from './api'
import AuthPanel from './AuthPanel'
import {
  TenantAgentTab, TenantInstitutionTab, TenantSessionsTab, TenantStatsTab, TenantSubTab,
  type TenantInfo,
} from './TenantAdmin'

/* ---------- SVG 图标 ---------- */
const Ic = ({ d }: { d: string }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
)
const NAV_ICONS: Record<string, ReactNode> = {
  docs: <Ic d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20 M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" />,
  ontology: <Ic d="M12 2 2 7l10 5 10-5-10-5Z M2 17l10 5 10-5 M2 12l10 5 10-5" />,
  agents: <Ic d="M12 8V4H8 M4 8h16v12H4Z M2 14h2 M20 14h2 M15 13v2 M9 13v2" />,
  analytics: <Ic d="M3 3v18h18 M8 16v-5 M12 16V8 M16 16v-8" />,
  leads: <Ic d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z M20 8v6 M23 11h-6" />,
  system: <Ic d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />,
  sessions: <Ic d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" />,
  board: <Ic d="M3 3v18h18 M8 16v-5 M12 16V8 M16 16v-8 M7 4h10" />,
  tenants: <Ic d="M3 21h18 M5 21V7l7-4 7 4v14 M9 9h1 M9 13h1 M14 9h1 M14 13h1" />,
  plans: <Ic d="M12 1v22 M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />,
  orders: <Ic d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z M14 2v6h6 M9 13h6 M9 17h6" />,
  materials: <Ic d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z M14 2v6h6 M12 18v-6 M9 15l3 3 3-3" />,
  usage: <Ic d="M3 3v18h18 M8 16v-5 M12 16V8 M16 16v-8" />,
  sub: <Ic d="M2 12h4l3-9 4 18 3-9h6" />,
  institution: <Ic d="M3 21h18 M5 21V8l7-4 7 4v13 M9 11h1 M9 15h1 M14 11h1 M14 15h1" />,
}

const AGENTS = [
  { key: 'student', label: '学生智能体', sub: '学生 / 家长入口 · /s', endpoint: '/mcp/student', welcomeFile: 'welcome_student.md' },
  { key: 'teacher', label: '教师智能体', sub: '教师入口 · /t', endpoint: '/mcp/teacher', welcomeFile: 'welcome_teacher.md' },
  { key: 'platform', label: '平台智能体', sub: '机构 / 企业入口 · /c', endpoint: '/mcp', welcomeFile: 'welcome_platform.md' },
]

/* 按智能体可配置的扩展能力 */
const CAPABILITIES = [
  { key: 'lead_capture', label: '留资转线索', desc: '用户表达报名意向时采集联系方式,转线索跟进' },
  { key: 'quality_check', label: '对话质检', desc: '对该智能体的会话进行质检评分' },
]

/* ---------- 知识域 / 知识库 / 文档 ---------- */
function DomainsTab() {
  const [domains, setDomains] = useState<any[]>([])
  const [selDom, setSelDom] = useState<number | null>(null)
  const [kbs, setKbs] = useState<any[]>([])
  const [selKb, setSelKb] = useState<number | null>(null)
  const [docs, setDocs] = useState<any[]>([])
  const [creatingDom, setCreatingDom] = useState(false)
  const [domForm, setDomForm] = useState({ name: '', description: '' })
  const [editingDom, setEditingDom] = useState(false)
  const [domEdit, setDomEdit] = useState({ name: '', description: '' })
  const [creatingKb, setCreatingKb] = useState(false)
  const [kbForm, setKbForm] = useState({ name: '', description: '' })
  const [title, setTitle] = useState('')
  const [processing, setProcessing] = useState('')   // 后台摄入中的文件名(空=无)
  const fileRef = useRef<HTMLInputElement>(null)

  const loadDomains = useCallback(() => api('/api/portal/domains').then(r => {
    setDomains(r)
    setSelDom(s => s ?? (r[0]?.id ?? null))
  }), [])
  const loadKbs = useCallback(() => {
    if (selDom) api('/api/portal/kbs?domain_id=' + selDom).then(r => {
      setKbs(r)
      setSelKb(s => (s && r.some((k: any) => k.id === s)) ? s : (r[0]?.id ?? null))
    })
    else { setKbs([]); setSelKb(null) }
  }, [selDom])
  const loadDocs = useCallback(() => {
    if (selKb) api('/api/portal/documents?kb_id=' + selKb).then(setDocs).catch(alert)
    else setDocs([])
  }, [selKb])
  useEffect(() => { loadDomains() }, [loadDomains])
  useEffect(() => { loadKbs() }, [loadKbs])
  useEffect(() => { loadDocs() }, [loadDocs])

  const dom = domains.find(d => d.id === selDom)
  const kb = kbs.find(k => k.id === selKb)

  async function createDom() {
    if (!domForm.name.trim()) return alert('请填写知识域名称')
    await api('/api/portal/domains', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(domForm),
    })
    setCreatingDom(false)
    setDomForm({ name: '', description: '' })
    loadDomains()
  }
  async function delDom() {
    if (!dom) return
    if (!confirm(`删除知识域「${dom.name}」及其下全部知识库、文档与本体?`)) return
    await api(`/api/portal/domains/${dom.id}`, { method: 'DELETE' })
    setSelDom(null)
    loadDomains()
  }
  async function renameDom() {
    if (!dom) return
    setDomEdit({ name: dom.name, description: dom.description || '' })
    setEditingDom(true)
  }
  async function saveDom() {
    if (!dom) return
    if (!domEdit.name.trim()) return alert('请填写知识域名称')
    await api(`/api/portal/domains/${dom.id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: domEdit.name.trim(),
        description: domEdit.description.trim(),
      }),
    })
    setEditingDom(false)
    loadDomains()
  }
  async function createKb() {
    if (!kbForm.name.trim()) return alert('请填写知识库名称')
    if (!selDom) return
    await api('/api/portal/kbs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...kbForm, domain_id: selDom }),
    })
    setCreatingKb(false)
    setKbForm({ name: '', description: '' })
    loadKbs(); loadDomains()
  }
  async function delKb(k: any) {
    if (!confirm(`删除知识库「${k.name}」及其全部文档与知识块?`)) return
    await api(`/api/portal/kbs/${k.id}`, { method: 'DELETE' })
    loadKbs(); loadDomains()
  }
  async function upload() {
    const f = fileRef.current?.files?.[0]
    if (!f) return alert('请先选择文件(.txt / .docx / .doc / .pdf)')
    if (!selKb) return alert('请先选择知识库')
    const fd = new FormData()
    fd.append('file', f)
    fd.append('kb_id', String(selKb))
    fd.append('title', title || f.name.replace(/\.[^.]+$/, ''))
    try {
      await api('/api/portal/documents', { method: 'POST', body: fd })
      setProcessing(f.name)          // 后台异步摄入,立即返回;轮询状态直至完成
      setTitle('')
      if (fileRef.current) fileRef.current.value = ''
      loadDocs()
    } catch (e: any) { alert('上传失败:' + e.message) }
  }

  // 后台摄入期间每 2.5s 轮询文档列表;全部不再 ingesting 后停止并刷新计数
  useEffect(() => {
    if (!processing) return
    const t = setInterval(loadDocs, 2500)
    return () => clearInterval(t)
  }, [processing, loadDocs])
  useEffect(() => {
    if (processing && docs.length && !docs.some((d: any) => d.status === 'ingesting')) {
      setProcessing('')
      loadKbs(); loadDomains()
    }
  }, [docs, processing])
  async function removeDoc(id: number, name: string) {
    if (!confirm(`删除文档「${name}」及其全部知识块与本体记录?`)) return
    await api(`/api/portal/documents/${id}`, { method: 'DELETE' })
    loadDocs(); loadKbs(); loadDomains()
  }

  return (
    <div className="p-docgrid">
      <div className="p-kblist">
        {domains.map(d => (
          <button key={d.id} className={`p-kb ${d.id === selDom ? 'on' : ''}`}
            onClick={() => { setSelDom(d.id); setEditingDom(false) }}>
            <b>{d.name}</b>
            <small>{d.description || '—'}</small>
            <span className="meta">
              <span className="p-mat">{d.kbs} 知识库</span>
              <span className="p-count">{d.entities} 实体 · {d.rules} 规则</span>
            </span>
          </button>
        ))}
        {creatingDom
          ? (
            <div className="p-kbform">
              <input placeholder="知识域名称" value={domForm.name}
                onChange={e => setDomForm({ ...domForm, name: e.target.value })} />
              <input placeholder="描述(可选)" value={domForm.description}
                onChange={e => setDomForm({ ...domForm, description: e.target.value })} />
              <div className="p-kbform-btns">
                <button onClick={createDom}>创建</button>
                <button className="ghost" onClick={() => setCreatingDom(false)}>取消</button>
              </div>
            </div>
          )
          : <button className="p-kb-new" onClick={() => setCreatingDom(true)}>+ 新建知识域</button>}
      </div>

      <div className="p-card">
        {dom
          ? (
            <>
              {editingDom ? (
                <div className="p-domedit">
                  <label>名称
                    <input value={domEdit.name}
                      onChange={e => setDomEdit({ ...domEdit, name: e.target.value })} />
                  </label>
                  <label>描述
                    <input value={domEdit.description} placeholder="可选,例如:北京/上海线下班、线上直播班,营期、费用与物资"
                      onChange={e => setDomEdit({ ...domEdit, description: e.target.value })} />
                  </label>
                  <div className="p-kbform-btns">
                    <button onClick={saveDom}>保存</button>
                    <button className="ghost" onClick={() => setEditingDom(false)}>取消</button>
                  </div>
                </div>
              ) : (
                <div className="p-kbhead">
                  <div>
                    <b>{dom.name}</b>
                    <small>{dom.description || '—'} · {dom.code}</small>
                  </div>
                  <span>
                    <button className="p-mini" onClick={renameDom}>编辑</button>
                    <button className="p-mini danger" onClick={delDom}>删除知识域</button>
                  </span>
                </div>
              )}

              <h3>知识库</h3>
              <div className="p-kbchips">
                {kbs.map(k => (
                  <button key={k.id} className={`p-kbchip ${k.id === selKb ? 'on' : ''}`}
                    onClick={() => setSelKb(k.id)}>
                    <b>{k.name}</b><span>{k.docs} 篇</span>
                    <i onClick={e => { e.stopPropagation(); delKb(k) }}>×</i>
                  </button>
                ))}
                {creatingKb
                  ? (
                    <span className="p-kbform-inline">
                      <input placeholder="知识库名称" value={kbForm.name}
                        onChange={e => setKbForm({ ...kbForm, name: e.target.value })} />
                      <button onClick={createKb}>创建</button>
                      <button className="ghost" onClick={() => setCreatingKb(false)}>取消</button>
                    </span>
                  )
                  : <button className="p-kbchip add" onClick={() => setCreatingKb(true)}>+ 新建知识库</button>}
              </div>

              {kb
                ? (
                  <>
                    <div className="p-toolbar">
                      <input ref={fileRef} type="file" accept=".txt,.docx,.doc,.pdf" />
                      <input placeholder="文档标题(可选)" value={title} onChange={e => setTitle(e.target.value)} />
                      <button onClick={upload} disabled={!!processing}>上传并摄入</button>
                      {processing && <span className="p-busy">解析与知识抽取中(后台异步,可继续操作)…</span>}
                    </div>
                    <table className="p-table">
                      <thead><tr><th>ID</th><th>文件</th><th>状态</th><th>知识块</th><th>实体</th><th>上传时间</th><th></th></tr></thead>
                      <tbody>
                        {docs.map(d => (
                          <tr key={d.id}>
                            <td>{d.id}</td>
                            <td>{d.filename}</td><td>{d.status}</td>
                            <td>{d.chunks}</td><td>{d.entities}</td>
                            <td className="p-src">{d.uploaded_at}</td>
                            <td><button className="p-mini danger" onClick={() => removeDoc(d.id, d.filename)}>删除</button></td>
                          </tr>
                        ))}
                        {!docs.length && <tr><td colSpan={7} className="p-src">该知识库暂无文档</td></tr>}
                      </tbody>
                    </table>
                  </>
                )
                : <div className="p-empty">请先创建或选择一个知识库</div>}
            </>
          )
          : <div className="p-empty">请先创建或选择一个知识域</div>}
      </div>
    </div>
  )
}

/* ---------- 智能体设置 ---------- */
export function AgentsTab() {
  const [sel, setSel] = useState('student')
  const [agents, setAgents] = useState<any>({})
  const [domains, setDomains] = useState<any[]>([])
  const [prompt, setPrompt] = useState('')
  const [welcome, setWelcome] = useState('')
  const [msg, setMsg] = useState('')
  const [models, setModels] = useState<{ model: string; name: string }[]>([])
  const [sysModel, setSysModel] = useState('')
  const [channels, setChannels] = useState<any[]>([])

  const agent = AGENTS.find(a => a.key === sel)!
  const loadAll = useCallback(() => {
    api('/api/portal/agents').then(setAgents).catch(alert)
    api('/api/portal/domains').then(setDomains).catch(alert)
    api('/api/portal/channels').then(setChannels).catch(() => {})
    api('/api/portal/llm').then(c => {
      const cc = c || {}
      const raw = Array.isArray(cc.chat_models) ? cc.chat_models : []
      const list = raw
        .map((m: any) => typeof m === 'string'
          ? { model: m, name: '' }
          : { model: m.model || '', name: m.name || '' })
        .filter((m: any) => m.model)
      if (!list.length && cc.chat_model) list.push({ model: cc.chat_model, name: '' })
      setModels(list)
      setSysModel(cc.chat_model || '')
    }).catch(() => {})
  }, [])
  useEffect(() => { loadAll() }, [loadAll])
  useEffect(() => {
    setMsg('')
    api(`/api/portal/config/prompts/${sel}.md`).then(r => setPrompt(r.content))
      .catch(() => setPrompt(''))
    api(`/api/portal/config/prompts/${agent.welcomeFile}`).then(r => setWelcome(r.content))
      .catch(() => setWelcome(''))
  }, [sel, agent.welcomeFile])

  function flash(t: string) { setMsg(t); setTimeout(() => setMsg(''), 3500) }

  async function toggleDomain(code: string) {
    const cur: string[] = (agents[sel]?.domains) || []
    const next = cur.includes(code) ? cur.filter(c => c !== code) : [...cur, code]
    const body = { [sel]: { domains: next } }
    const r = await api('/api/portal/agents', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    setAgents(r.agents)
    flash('知识域对接已保存 · 即时生效')
  }
  async function setAgentModel(model: string) {
    const r = await api('/api/portal/agents', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [sel]: { model } }),
    })
    setAgents(r.agents)
    const label = models.find(m => m.model === model)?.name || model
    flash(model ? `对话模型已切换为 ${label}` : '已恢复系统默认模型')
  }
  async function toggleCapability(capKey: string) {
    const cur = (agents[sel]?.capabilities || {}) as Record<string, boolean>
    const next = { ...cur, [capKey]: !cur[capKey] }
    const r = await api('/api/portal/agents', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [sel]: { capabilities: next } }),
    })
    setAgents(r.agents)
    flash('能力配置已保存 · 即时生效')
  }
  async function savePrompt() {
    await api(`/api/portal/config/prompts/${sel}.md`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: prompt }),
    })
    flash('系统提示词已保存 · 热加载生效')
  }
  async function saveWelcome() {
    await api(`/api/portal/config/prompts/${agent.welcomeFile}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: welcome }),
    })
    flash('欢迎词已保存 · 热加载生效')
  }

  const origin = window.location.origin
  const endpoint = origin + agent.endpoint
  const activeToken = (channels.find(c => !c.disabled) || {}).token || ''
  const MCP_DESC: Record<string, string> = {
    student: '学生课程顾问 MCP(夏令营班型推荐/确定性费用计算/详情问答/报名引导,知识范围限学生知识域)',
    teacher: '教师培训顾问 MCP(L1—L3 培训推荐/确定性费用计算/前置与报名,知识范围限教师知识域)',
    platform: '平台服务顾问 MCP(平台与会员服务咨询,通用入口)',
  }
  const mcpJson = JSON.stringify({
    [`opc-course-advisor-${sel}`]: {
      type: 'http',
      url: endpoint,
      headers: { Authorization: `Bearer ${activeToken || '<在系统设置·渠道令牌签发>'}` },
      description: MCP_DESC[sel] || '',
      disabled: false,
    },
  }, null, 2)

  function copy(text: string) {
    navigator.clipboard?.writeText(text).then(() => flash('已复制到剪贴板')).catch(() => flash('复制失败,请手动选择'))
  }

  const selected: string[] = agents[sel]?.domains || []

  return (
    <>
      <div className="p-docgrid">
        <div className="p-kblist">
          {AGENTS.map(a => (
            <button key={a.key} className={`p-kb ${a.key === sel ? 'on' : ''}`} onClick={() => setSel(a.key)}>
              <b>{a.label}</b>
              <small>{a.sub}</small>
              <span className="meta">
                <span className="p-mono">{a.endpoint}</span>
                <span className="p-count">{(agents[a.key]?.domains || []).length} 知识域</span>
              </span>
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
          <div className="p-card">
            <h3>推理模型</h3>
            <p className="p-scope-hint">
              为该智能体选择对话模型(选项来自「模型及参数 → 支持的模型」);不选则跟随系统默认模型。
              切换即时生效,仅影响本智能体的对话生成。
            </p>
            <div className="p-modelpick">
              <select value={(agents[sel]?.model as string) || ''}
                onChange={e => setAgentModel(e.target.value)}>
                <option value="">
                  系统默认模型{sysModel ? `(${models.find(m => m.model === sysModel)?.name || sysModel})` : ''}
                </option>
                {models.map(m => (
                  <option key={m.model} value={m.model}>
                    {m.name ? `${m.name}(${m.model})` : m.model}
                  </option>
                ))}
              </select>
              {msg && <span className="p-ok">{msg}</span>}
            </div>
          </div>

          <div className="p-card">
            <h3>能力配置</h3>
            <p className="p-scope-hint">
              按智能体启用的扩展能力(留资转人工 / 对话质检 / 早鸟截止提醒),保存后即时生效。
            </p>
            <div className="p-caps">
              {CAPABILITIES.map(c => {
                const on = !!((agents[sel]?.capabilities || {})[c.key])
                return (
                  <label key={c.key} className={`p-cap ${on ? 'on' : ''}`}
                    onClick={() => toggleCapability(c.key)}>
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
              勾选 {agent.label} 可引用的知识域。<b>未勾选知识域的内容不参与该智能体的检索、推荐与计算</b>;
              勾选变更立即保存并生效。
            </p>
            <div className="p-checks">
              {domains.map(d => (
                <label key={d.code} className={selected.includes(d.code) ? 'on' : ''}>
                  <input type="checkbox" checked={selected.includes(d.code)}
                    onChange={() => toggleDomain(d.code)} />
                  <span><b>{d.name}</b><small>{d.description || d.code}</small></span>
                </label>
              ))}
            </div>
          </div>

          <div className="p-card">
            <h3>系统提示词(prompts/{sel}.md)</h3>
            <p className="p-scope-hint">定义该智能体的身份、服务流程、红线规则与回答风格;保存后热加载生效。</p>
            <textarea className="p-scope-editor" rows={16} value={prompt}
              onChange={e => setPrompt(e.target.value)} />
            <div className="p-toolbar" style={{ marginTop: 12 }}>
              <button onClick={savePrompt}>保存提示词</button>
              {msg && <span className="p-ok">{msg}</span>}
            </div>
          </div>

          <div className="p-card">
            <h3>欢迎词(prompts/{agent.welcomeFile})</h3>
            <p className="p-scope-hint">新会话第一条消息(固定模板);保存后热加载生效。</p>
            <textarea className="p-scope-editor" rows={9} value={welcome}
              onChange={e => setWelcome(e.target.value)} />
            <div className="p-toolbar" style={{ marginTop: 12 }}>
              <button onClick={saveWelcome}>保存欢迎词</button>
            </div>
          </div>

          <div className="p-card">
            <h3>MCP 接入</h3>
            <p className="p-scope-hint">
              {agent.label}的独立 MCP 端点(HTTP),工具调用自动限定在上述知识域内,
              经渠道令牌(Bearer)鉴权。将以下条目粘贴进 TRAE / WorkBuddy / OpenClaw 等
              宿主 MCP 配置文件的 <b>mcpServers</b> 节点即可:
            </p>
            {!activeToken && (
              <p className="p-err" style={{ marginBottom: 10 }}>
                ⚠ 尚无有效渠道令牌:系统一旦签发令牌,MCP 将强制校验。请先到「系统设置 → 渠道令牌」签发。
              </p>
            )}
            <div className="p-endpoint">
              <code>{endpoint}</code>
              <button className="p-mini" onClick={() => copy(endpoint)}>复制地址</button>
            </div>
            <pre className="p-json">{mcpJson}</pre>
            <div className="p-toolbar">
              <button onClick={() => copy(mcpJson)}>复制 JSON 配置</button>
              <span className="p-count">Authorization 中的令牌可在「系统设置 → 渠道令牌」更换或禁用</span>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

/* ---------- 系统设置(模型服务 · API Key · 全局参数) ---------- */
function SystemTab() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <LlmConfigCard />
      <ChannelsCard />
    </div>
  )
}

/* ---------- 渠道令牌(MCP 接入鉴权) ---------- */
function ChannelsCard() {
  const [channels, setChannels] = useState<any[]>([])
  const [name, setName] = useState('')
  const [msg, setMsg] = useState('')
  const [showToken, setShowToken] = useState<Record<number, boolean>>({})
  const origin = window.location.origin
  const load = useCallback(() => { api('/api/portal/channels').then(setChannels).catch(alert) }, [])
  useEffect(() => { load() }, [load])
  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(''), 3000) }
  async function create() {
    if (!name.trim()) return alert('请填写渠道名称')
    await api('/api/portal/channels', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim() }),
    })
    setName('')
    load()
  }
  async function toggle(c: any) {
    await api(`/api/portal/channels/${c.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ disabled: !c.disabled }),
    })
    load()
  }
  async function remove(c: any) {
    if (!confirm(`删除渠道「${c.name}」?删除后使用该令牌的连接将失效。`)) return
    await api(`/api/portal/channels/${c.id}`, { method: 'DELETE' })
    load()
  }
  function copyCfg(c: any) {
    const slug = c.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'channel'
    const cfg = {
      [slug]: {
        type: 'http',
        url: origin + '/mcp',
        headers: { Authorization: `Bearer ${c.token}` },
        description: `${c.name} MCP`,
        disabled: false,
      },
    }
    navigator.clipboard?.writeText(JSON.stringify(cfg, null, 2))
      .then(() => flash('MCP 配置已复制'))
      .catch(() => flash('复制失败,请手动复制令牌'))
  }
  return (
    <div className="p-card">
      <h3>渠道令牌(MCP 接入鉴权)</h3>
      <p className="p-scope-hint">
        为不同渠道(第三方 Agent / 合作系统)签发令牌,用于接入 MCP 端点(请求头携带
        <code> Authorization: Bearer &lt;token&gt;</code>)。
        <b>一旦存在有效令牌,MCP 连接需携带有效令牌;尚无任何令牌时保持开放兼容。</b>
      </p>
      <div className="p-toolbar">
        <input placeholder="渠道名称(如 WorkBuddy、某合作系统)" value={name}
          onChange={e => setName(e.target.value)} onKeyDown={e => e.key === 'Enter' && create()} />
        <button onClick={create}>签发令牌</button>
        {msg && <span className="p-ok">{msg}</span>}
      </div>
      <table className="p-table">
        <thead><tr><th>渠道</th><th>令牌</th><th>状态</th><th>最近使用</th><th>操作</th></tr></thead>
        <tbody>
          {channels.map(c => (
            <tr key={c.id}>
              <td>{c.name}</td>
              <td className="p-mono">
                {showToken[c.id] ? c.token : c.token.slice(0, 10) + '••••••••'}
                <button className="p-mini" style={{ marginLeft: 6 }}
                  onClick={() => setShowToken(s => ({ ...s, [c.id]: !s[c.id] }))}>
                  {showToken[c.id] ? '隐藏' : '显示'}
                </button>
              </td>
              <td><span className={`p-lead-st ${c.disabled ? 'invalid' : 'converted'}`}>{c.disabled ? '已禁用' : '启用'}</span></td>
              <td className="p-src">{c.last_used_at || '—'}</td>
              <td className="p-ops">
                <button className="p-mini" onClick={() => copyCfg(c)}>复制配置</button>
                <button className="p-mini" onClick={() => toggle(c)}>{c.disabled ? '启用' : '禁用'}</button>
                <button className="p-mini danger" onClick={() => remove(c)}>删除</button>
              </td>
            </tr>
          ))}
          {!channels.length && <tr><td colSpan={5} className="p-src">暂无渠道令牌(当前 MCP 开放访问)</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

/* ---------- 模型及参数(llm.yaml 结构化配置) ---------- */
const LLM_FIELDS: { key: string; label: string; type: 'text' | 'number' | 'select'; hint?: string; options?: string[] }[] = [
  { key: 'embedding_model', label: '向量模型(全平台统一)', type: 'text', hint: '文档向量化与对话检索向量化共用,不按智能体单独设置' },
  { key: 'rerank_model', label: '重排模型(全平台统一)', type: 'text', hint: '检索结果重排序' },
  { key: 'rerank_strategy', label: '重排策略', type: 'select', options: ['llm', 'endpoint'], hint: 'llm=模型打分(任意环境可用);endpoint=调用重排端点' },
  { key: 'rerank_url', label: '重排端点地址', type: 'text', hint: '仅策略为 endpoint 时生效' },
  { key: 'temperature', label: 'Temperature', type: 'number', hint: '生成随机性,0–2' },
  { key: 'max_tokens', label: '最大输出 max_tokens', type: 'number' },
  { key: 'request_timeout', label: '请求超时(秒)', type: 'number' },
  { key: 'context_turns', label: '上下文轮次', type: 'number', hint: '每轮注入的历史消息条数;0 或负数 = 不限制' },
]

function LlmConfigCard() {
  const [cfg, setCfg] = useState<Record<string, any>>({})
  const [models, setModels] = useState<{ model: string; name: string }[]>([])
  const [showKey, setShowKey] = useState(false)
  const [msg, setMsg] = useState('')
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    api('/api/portal/llm').then(c => {
      const cc = c || {}
      setCfg(cc)
      const raw = Array.isArray(cc.chat_models) ? cc.chat_models : []
      const list = raw.map((m: any) => typeof m === 'string'
        ? { model: m, name: '' }
        : { model: m.model || '', name: m.name || '' })
      if (!list.length && cc.chat_model) list.push({ model: cc.chat_model, name: '' })
      setModels(list.length ? list : [{ model: '', name: '' }])
      setLoaded(true)
    }).catch(alert)
  }, [])
  function setField(key: string, v: any) { setCfg(c => ({ ...c, [key]: v })) }
  function setModelAt(i: number, patch: Partial<{ model: string; name: string }>) {
    setModels(ms => ms.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  }
  async function save() {
    const body: Record<string, any> = {
      chat_models: models
        .map(m => ({ model: (m.model || '').trim(), name: (m.name || '').trim() }))
        .filter(m => m.model),
      api_key: (cfg.api_key ?? '').trim(),
      base_url: (cfg.base_url ?? '').trim(),
    }
    for (const f of LLM_FIELDS) {
      const raw = cfg[f.key]
      if (raw === '' || raw == null) continue
      body[f.key] = f.type === 'number' ? Number(raw) : raw
    }
    await api('/api/portal/llm', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    setMsg('已保存 · 热加载即时生效')
    setTimeout(() => setMsg(''), 3500)
  }
  return (
    <div className="p-card">
      <h3>模型及参数(llm.yaml)</h3>
      <p className="p-scope-hint">对话服务与模型清单在此统一维护;各智能体可从「支持的模型」中选择自己的对话模型。向量/重排模型全平台统一。保存后热加载即时生效。</p>
      {loaded ? (
        <>
          <div className="p-llmgrid">
            <label className="p-llmfield">
              <span className="p-llmlabel">对话服务地址(URL)</span>
              <input type="text" value={cfg.base_url ?? ''} onChange={e => setField('base_url', e.target.value)} />
              <em>OpenAI 兼容接口地址</em>
            </label>
            <label className="p-llmfield">
              <span className="p-llmlabel">API Key</span>
              <span className="p-keywrap">
                <input type={showKey ? 'text' : 'password'} value={cfg.api_key ?? ''}
                  placeholder="留空则回退环境变量 VOLCANO_API_KEY"
                  onChange={e => setField('api_key', e.target.value)} />
                <button type="button" className="p-keytoggle" onClick={() => setShowKey(v => !v)}>
                  {showKey ? '隐藏' : '显示'}
                </button>
              </span>
              <em>写入服务端 llm.yaml(不入库、不随部署覆盖)</em>
            </label>
            <div className="p-llmfield" style={{ gridColumn: '1 / -1' }}>
              <span className="p-llmlabel">支持的模型(各智能体可切换的对话模型)</span>
              <div className="p-models">
                <div className="p-modelhead">
                  <span>模型 ID(实际调用所用)</span>
                  <span>显示名称(配置与展示用)</span>
                  <span />
                </div>
                {models.map((m, i) => (
                  <div key={i} className="p-modelrow">
                    <input type="text" value={m.model} placeholder="如 ep-20260513181443-mgmn4"
                      onChange={e => setModelAt(i, { model: e.target.value })} />
                    <input type="text" value={m.name} placeholder="如 豆包 Seed 1.6"
                      onChange={e => setModelAt(i, { name: e.target.value })} />
                    <button type="button" className="p-mini danger" title="移除"
                      onClick={() => setModels(ms => ms.filter((_, j) => j !== i))}>✕</button>
                  </div>
                ))}
                <button type="button" className="p-mini" onClick={() => setModels(ms => [...ms, { model: '', name: '' }])}>+ 添加模型</button>
              </div>
            </div>
          </div>
          <h4 className="p-subhead">生成与检索参数</h4>
          <div className="p-llmgrid">
            {LLM_FIELDS.map(f => (
              <label key={f.key} className="p-llmfield">
                <span className="p-llmlabel">{f.label}</span>
                {f.type === 'select' ? (
                  <select value={String(cfg[f.key] ?? '')} onChange={e => setField(f.key, e.target.value)}>
                    {(f.options || []).map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input type={f.type} step="any" value={cfg[f.key] ?? ''}
                    onChange={e => setField(f.key, e.target.value)} />
                )}
                {f.hint && <em>{f.hint}</em>}
              </label>
            ))}
          </div>
        </>
      ) : <div className="p-empty">加载中…</div>}
      <div className="p-toolbar" style={{ marginTop: 12 }}>
        <button onClick={save}>保存模型参数</button>
        {msg && <span className="p-ok">{msg}</span>}
      </div>
    </div>
  )
}

/* ---------- 会话查看 ---------- */
export function SessionsTab() {
  const [sessions, setSessions] = useState<any[]>([])
  const [sid, setSid] = useState('')
  const [msgs, setMsgs] = useState<any[]>([])
  const [qc, setQc] = useState<any>(null)
  const [checking, setChecking] = useState(false)
  const [batching, setBatching] = useState(false)
  const load = useCallback(() => { api('/api/portal/sessions').then(setSessions).catch(alert) }, [])
  useEffect(() => { load() }, [load])
  async function open(id: string) {
    setSid(id)
    setMsgs(await api(`/api/portal/sessions/${id}/messages`))
    const ql = await api(`/api/portal/quality?session_id=${id}`)
    setQc(ql && ql.length ? ql[0] : null)
  }
  async function checkOne() {
    if (!sid) return
    setChecking(true)
    try {
      const r = await api(`/api/portal/quality/${sid}`, { method: 'POST' })
      if (r.error) { alert(r.error) } else { setQc(r); load() }
    } catch (e: any) { alert('质检失败:' + e.message) } finally { setChecking(false) }
  }
  async function checkBatch() {
    if (!confirm('质检最近 10 个未质检会话?(每个会话一次 LLM 评分,约需数十秒)')) return
    setBatching(true)
    try {
      const r = await api('/api/portal/quality/batch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 10 }),
      })
      alert(`已质检 ${r.checked} 个会话`)
      load()
      if (sid) open(sid)
    } catch (e: any) { alert('批量质检失败:' + e.message) } finally { setBatching(false) }
  }
  const scoreClass = (s: number) => (s >= 85 ? 'good' : s >= 70 ? 'mid' : 'bad')
  const roleZh: Record<string, string> = { student: '学生', teacher: '教师', platform: '平台/机构' }
  return (
    <div className="p-sessions">
      <div className="p-card" style={{ flex: 1.15 }}>
        <div className="p-toolbar" style={{ marginBottom: 10 }}>
          <button onClick={checkBatch} disabled={batching}>{batching ? '质检中…' : '批量质检(最近10个)'}</button>
        </div>
        <table className="p-table">
          <thead><tr><th>会话</th><th>入口</th><th>消息</th><th>质检分</th><th>更新时间</th></tr></thead>
          <tbody>
            {sessions.map(s => (
              <tr key={s.id} className={s.id === sid ? 'on' : ''} onClick={() => open(s.id)}>
                <td className="p-mono">{s.id}</td>
                <td><span className="p-mat">{roleZh[s.role] || s.role}</span></td>
                <td>{s.msgs}</td>
                <td>{s.quality_score != null
                  ? <span className={`p-score ${scoreClass(s.quality_score)}`}>{s.quality_score}</span>
                  : <span className="p-score-none">未质检</span>}</td>
                <td className="p-src">{s.updated_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="p-card" style={{ flex: 1 }}>
        {sid ? (
          <>
            <div className="p-toolbar" style={{ marginBottom: 10 }}>
              <button onClick={checkOne} disabled={checking}>{checking ? '质检中…' : '质检此会话'}</button>
            </div>
            {qc && (
              <div className={`p-qc p-qc-${scoreClass(qc.score)}`}>
                <div className="p-qc-score"><b>{qc.score}</b><span>质检总分</span></div>
                <div className="p-qc-dims">
                  <span>准确 {qc.accuracy}</span><span>规范 {qc.compliance}</span><span>体验 {qc.experience}</span>
                </div>
                {qc.comment && <div className="p-qc-comment">{qc.comment}</div>}
                {qc.issues && qc.issues.length > 0 && (
                  <div className="p-qc-issues">
                    <b>问题:</b>
                    <ul>{qc.issues.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
                  </div>
                )}
              </div>
            )}
            <div className="p-msgs">{msgs.map((m, i) => (
              <div key={i} className={`p-msg ${m.role}`}>
                <b>{m.role}</b>
                {m.tool_calls ? <code>{JSON.stringify(m.tool_calls)}</code> : null}
                <div>{m.content}</div>
              </div>
            ))}</div>
          </>
        ) : <div className="p-empty">点击左侧会话查看消息明细,并可质检评分</div>}
      </div>
    </div>
  )
}

/* ---------- 主组件:左侧导航布局 ---------- */
/* ---------- 线索转化(留资转线索工单) ---------- */
const LEAD_STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: '待跟进', cls: 'pending' },
  followed: { label: '已跟进', cls: 'followed' },
  converted: { label: '已转化', cls: 'converted' },
  invalid: { label: '无效', cls: 'invalid' },
}
function LeadsTab() {
  const [leads, setLeads] = useState<any[]>([])
  const [status, setStatus] = useState('')
  const load = useCallback(() => {
    api(`/api/portal/leads?status=${status}`).then(setLeads).catch(alert)
  }, [status])
  useEffect(() => { load() }, [load])
  async function patch(id: number, body: any) {
    await api(`/api/portal/leads/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    load()
  }
  function follow(id: number) {
    const note = prompt('跟进记录(可选)')
    if (note === null) return
    patch(id, { status: 'followed', follow_note: note })
  }
  const roleZh = (r: string) => ({ student: '学生', teacher: '教师', platform: '平台' }[r] || r)
  return (
    <div className="p-card">
      <p className="p-scope-hint">
        智能体在对话中采集的用户报名意向(留资),在此转化为线索跟进。<b>仅做留资跟进流转,不做报名/支付管理。</b>
      </p>
      <div className="p-toolbar">
        <select value={status} onChange={e => setStatus(e.target.value)}>
          <option value="">全部状态</option>
          <option value="pending">待跟进</option>
          <option value="followed">已跟进</option>
          <option value="converted">已转化</option>
          <option value="invalid">无效</option>
        </select>
        <button onClick={load}>刷新</button>
      </div>
      <table className="p-table">
        <thead><tr><th>姓名</th><th>联系方式</th><th>意向</th><th>来源</th><th>状态</th><th>时间</th><th>操作</th></tr></thead>
        <tbody>
          {leads.map(l => (
            <tr key={l.id}>
              <td>{l.name || '—'}</td>
              <td className="p-mono">{l.phone || '—'}</td>
              <td title={l.note || ''}>{l.intent || '—'}</td>
              <td><span className="p-mat">{roleZh(l.agent_role)}</span></td>
              <td><span className={`p-lead-st ${LEAD_STATUS[l.status]?.cls}`}>{LEAD_STATUS[l.status]?.label}</span></td>
              <td className="p-src">{l.created_at}</td>
              <td className="p-ops">
                {l.status === 'pending' && <button className="p-mini" onClick={() => follow(l.id)}>跟进</button>}
                {l.status !== 'converted' && <button className="p-mini" onClick={() => patch(l.id, { status: 'converted' })}>已转化</button>}
                {l.status !== 'invalid' && <button className="p-mini danger" onClick={() => patch(l.id, { status: 'invalid' })}>无效</button>}
              </td>
            </tr>
          ))}
          {!leads.length && <tr><td colSpan={7} className="p-src">暂无工单</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

/* ---------- 数据分析(智能体运营分析) ---------- */
function AnalyticsTab() {
  const [role, setRole] = useState('')
  const [data, setData] = useState<any>(null)
  const [insight, setInsight] = useState<any>(null)
  const [genIng, setGenIng] = useState(false)
  const load = useCallback(() => {
    api(`/api/portal/analytics?role=${role}`).then(setData).catch(alert)
    api(`/api/portal/analytics/insight?role=${role}`).then(setInsight).catch(() => setInsight(null))
  }, [role])
  useEffect(() => { load() }, [load])
  async function genInsight() {
    setGenIng(true)
    try {
      const r = await api('/api/portal/analytics/insight', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      })
      setInsight(r)
    } catch (e: any) { alert('洞察生成失败:' + e.message) } finally { setGenIng(false) }
  }
  const ov = data?.overview || {}
  const maxQ = Math.max(1, ...(data?.top_questions || []).map((x: any) => x.c))
  const maxR = Math.max(1, ...(data?.recommend_dist || []).map((x: any) => x.count))
  const maxT = Math.max(1, ...(data?.trend || []).map((x: any) => x.c))
  const roleZh = (r: string) => ({ student: '学生', teacher: '教师', platform: '平台' }[r] || r)
  return (
    <div className="p-ana">
      <div className="p-toolbar">
        <select value={role} onChange={e => setRole(e.target.value)}>
          <option value="">全部智能体</option>
          <option value="student">学生智能体</option>
          <option value="teacher">教师智能体</option>
          <option value="platform">平台智能体</option>
        </select>
        <button onClick={load}>刷新</button>
      </div>

      <div className="p-stats">
        <div className="p-stat"><b>{ov.total_sessions ?? 0}</b><span>总会话数</span></div>
        <div className="p-stat"><b>{ov.total_questions ?? 0}</b><span>总提问数</span></div>
        {(data?.by_agent || []).map((a: any) => (
          <div className="p-stat" key={a.role}><b>{a.c}</b><span>{roleZh(a.role)}会话</span></div>
        ))}
        {(data?.quality || []).map((q: any) => (
          <div className="p-stat" key={'q' + q.role}><b>{q.avg_score}</b><span>{roleZh(q.role)}质检分</span></div>
        ))}
      </div>

      <div className="p-ana-grid">
        <div className="p-card">
          <h3>近 14 日会话趋势</h3>
          <div className="p-trend">
            {(data?.trend || []).map((t: any) => (
              <div className="p-trend-col" key={t.d} title={`${t.d}:${t.c}`}>
                <i style={{ height: `${Math.max(6, (t.c / maxT) * 100)}%` }} />
                <span>{t.d.slice(5)}</span>
              </div>
            ))}
            {!(data?.trend || []).length && <div className="p-empty">暂无数据</div>}
          </div>
        </div>

        <div className="p-card">
          <h3>推荐班型分布</h3>
          <div className="p-bars">
            {(data?.recommend_dist || []).map((x: any) => (
              <div className="p-bar-row" key={x.name}>
                <span className="p-bar-name" title={x.name}>{x.name}</span>
                <span className="p-bar-track"><i style={{ width: `${(x.count / maxR) * 100}%` }} /></span>
                <b>{x.count}</b>
              </div>
            ))}
            {!(data?.recommend_dist || []).length && <div className="p-empty">暂无推荐记录</div>}
          </div>
        </div>

        <div className="p-card">
          <h3>高频问题 TOP</h3>
          <div className="p-bars">
            {(data?.top_questions || []).map((x: any, i: number) => (
              <div className="p-bar-row" key={i}>
                <span className="p-bar-name" title={x.q}>{x.q}</span>
                <span className="p-bar-track"><i style={{ width: `${(x.c / maxQ) * 100}%` }} /></span>
                <b>{x.c}</b>
              </div>
            ))}
            {!(data?.top_questions || []).length && <div className="p-empty">暂无提问</div>}
          </div>
        </div>

        <div className="p-card">
          <h3>未答 / 边界问题(知识缺口)</h3>
          <div className="p-unans">
            {(data?.unanswered || []).map((u: any, i: number) => (
              <div className="p-unans-item" key={i}>{u.q}</div>
            ))}
            {!(data?.unanswered || []).length && <div className="p-empty">暂无未答问题</div>}
          </div>
        </div>
      </div>

      <div className="p-card">
        <div className="p-toolbar" style={{ marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>LLM 运营洞察</h3>
          <button onClick={genInsight} disabled={genIng}>{genIng ? '生成中…' : '生成/刷新洞察'}</button>
        </div>
        {insight?.content
          ? <div className="p-insight">{insight.content}</div>
          : <div className="p-empty">点击「生成/刷新洞察」,由 LLM 分析运营数据给出改进建议</div>}
      </div>
    </div>
  )
}

/* ---------- 租户看板(SaaS · echarts 图表) ---------- */
declare global { interface Window { echarts?: any } }

function loadEcharts(): Promise<void> {
  if (window.echarts) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = '/_shared/js/echarts.min.js'
    s.onload = () => resolve()
    s.onerror = reject
    document.head.appendChild(s)
  })
}

function BoardTab() {
  const [data, setData] = useState<any>(null)
  const [tenants, setTenants] = useState<any[]>([])
  const trendRef = useRef<HTMLDivElement>(null)
  const barRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    Promise.all([api('/api/portal/dashboard'), api('/api/portal/tenants')])
      .then(([d, ts]) => { setData(d); setTenants(Array.isArray(ts) ? ts : []) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!data) return
    let charts: any[] = []
    loadEcharts().then(() => {
      const ec = window.echarts
      if (!ec) return
      if (trendRef.current) {
        const c1 = ec.init(trendRef.current)
        c1.setOption({
          tooltip: { trigger: 'axis' },
          grid: { left: 42, right: 16, top: 32, bottom: 30 },
          xAxis: { type: 'category', data: data.trend.map((x: any) => x.date.slice(5)) },
          yAxis: { type: 'value', minInterval: 1 },
          series: [{ name: '新增会话', type: 'line', smooth: true,
            areaStyle: { opacity: 0.14 }, itemStyle: { color: '#CA8A04' },
            data: data.trend.map((x: any) => x.count) }],
        })
        charts.push(c1)
      }
      if (barRef.current && data.top_tenants?.length) {
        const c2 = ec.init(barRef.current)
        const rows = [...data.top_tenants].reverse()
        c2.setOption({
          tooltip: {},
          grid: { left: 130, right: 24, top: 24, bottom: 30 },
          xAxis: { type: 'value', minInterval: 1 },
          yAxis: { type: 'category', data: rows.map((x: any) => x.name) },
          series: [{ name: '对话数', type: 'bar', barWidth: 16,
            itemStyle: { color: '#1B2942', borderRadius: 4 },
            data: rows.map((x: any) => x.chats) }],
        })
        charts.push(c2)
      }
      const onResize = () => charts.forEach(c => c.resize())
      window.addEventListener('resize', onResize)
      return () => window.removeEventListener('resize', onResize)
    }).catch(() => {})
    return () => { charts.forEach(c => c.dispose()); charts = [] }
  }, [data])

  const totals = data?.totals || {}
  return (
    <div>
      <div className="p-statrow">
        {[['租户机构', totals.tenants], ['用户数', totals.users],
          ['会话数', totals.sessions], ['对话次数', totals.chats]].map(([k, v]) => (
          <div className="p-stat" key={k as string}><em>{v ?? '—'}</em><span>{k}</span></div>
        ))}
      </div>
      <div className="board-charts">
        <div className="board-chart-box">
          <h4>近 14 日会话趋势(全平台)</h4>
          <div ref={trendRef} className="board-chart" />
        </div>
        <div className="board-chart-box">
          <h4>租户对话数排行</h4>
          <div ref={barRef} className="board-chart" />
        </div>
      </div>
      <table className="board-table">
        <thead><tr><th>租户</th><th>标识</th><th>套餐</th><th>用户</th><th>会话</th><th>对话数</th><th>开通时间</th></tr></thead>
        <tbody>
          {tenants.map(x => (
            <tr key={x.id}>
              <td><b>{x.name}</b></td>
              <td className="p-mono">{x.slug}</td>
              <td>{x.plan_code === 'pro' ? '专业版' : '免费版'}</td>
              <td>{x.users}</td><td>{x.sessions}</td><td>{x.chats}</td>
              <td>{x.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ---------- 平台经营:租户管理 / 套餐定价 / 订单管理 ---------- */

function TenantsTab() {
  const [rows, setRows] = useState<any[]>([])
  const load = useCallback(() => { api('/api/portal/tenants').then(setRows).catch(() => {}) }, [])
  useEffect(load, [load])
  return (
    <table className="board-table">
      <thead><tr><th>ID</th><th>机构</th><th>标识</th><th>套餐</th><th>用户</th><th>会话</th><th>对话数</th><th>累计用量</th><th>开通时间</th></tr></thead>
      <tbody>
        {rows.map(x => (
          <tr key={x.id}>
            <td>{x.id}</td>
            <td><b>{x.name}</b></td>
            <td className="p-mono">{x.slug}</td>
            <td>{x.plan_code === 'flagship' ? '旗舰版' : x.plan_code === 'standard' ? '标准版' : (x.plan_code || '—')}</td>
            <td>{x.users}</td><td>{x.sessions}</td><td>{x.chats}</td><td>{x.total_usage}</td>
            <td>{x.created_at}</td>
          </tr>
        ))}
        {!rows.length && <tr><td colSpan={9} className="tadm-empty">暂无租户</td></tr>}
      </tbody>
    </table>
  )
}

function PlansTab() {
  const [rows, setRows] = useState<any[]>([])
  const [msg, setMsg] = useState('')
  const load = useCallback(() => { api('/api/portal/plans').then(setRows).catch(() => {}) }, [])
  useEffect(load, [load])
  async function save(code: string, patch: Record<string, unknown>) {
    setMsg('')
    try {
      await api(`/api/portal/plans/${code}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      setMsg('已保存')
      load()
    } catch (e: any) { setMsg(e.message || '保存失败') }
  }
  return (
    <div>
      {msg && <div className="tadm-ok" style={{ marginBottom: 10 }}>{msg}</div>}
      <table className="board-table">
        <thead><tr><th>套餐</th><th>月价(¥)</th><th>对话限额</th><th>开通租户数</th><th>功能</th><th /></tr></thead>
        <tbody>
          {rows.map(p => (
            <PlanRow key={p.code} plan={p} onSave={save} />
          ))}
        </tbody>
      </table>
      <p style={{ marginTop: 12, fontSize: 12, color: 'var(--mut)' }}>
        定价为演示数据,可在线调整;功能范围由套餐定义决定(标准版=知识域智能体,旗舰版=全部功能)。
      </p>
    </div>
  )
}

function PlanRow({ plan, onSave }: { plan: any; onSave: (code: string, patch: Record<string, unknown>) => void }) {
  const [name, setName] = useState(plan.name)
  const [price, setPrice] = useState(String(plan.price_monthly))
  const FEATURE_LABELS: Record<string, string> = {
    agent_settings: '智能体设置', agent_caps: '能力开关', domains: '知识域管理',
    rag_manage: '课程资料管理', ontology: '本体图谱', sessions: '对话记录',
    leads: '线索转化', analytics: '运营分析', skills: 'Agent Skill',
  }
  const feats = Object.entries(plan.features || {})
    .filter(([, v]) => v === true)
    .map(([k]) => FEATURE_LABELS[k] || k)
  return (
    <tr>
      <td>
        <input value={name} onChange={e => setName(e.target.value)}
          style={{ width: 100, padding: '5px 8px', border: '1px solid var(--line)', borderRadius: 7, fontWeight: 700 }} />
        <small className="p-mono"> {plan.code}</small>
      </td>
      <td style={{ width: 130 }}>
        <input value={price} onChange={e => setPrice(e.target.value)}
          style={{ width: 90, padding: '5px 8px', border: '1px solid var(--line)', borderRadius: 7 }} />
      </td>
      <td>{plan.chat_limit_month < 0 ? '不限' : plan.chat_limit_month}</td>
      <td>{plan.active_subs}</td>
      <td style={{ fontSize: 12 }}>{feats.join(' · ')}</td>
      <td>
        <button className="tadm-del" style={{ color: 'var(--ink)' }}
          onClick={() => onSave(plan.code, { name, price_monthly: Number(price) })}>保存</button>
      </td>
    </tr>
  )
}

function OrdersTab() {
  const [rows, setRows] = useState<any[]>([])
  const [status, setStatus] = useState('')
  const load = useCallback(() => { api('/api/portal/orders').then(setRows).catch(() => {}) }, [])
  useEffect(load, [load])
  const shown = status ? rows.filter(r => r.status === status) : rows
  return (
    <div>
      <div className="tadm-filter" style={{ marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>支付订单({shown.length})</h3>
        <div className="tadm-range">
          <select value={status} onChange={e => setStatus(e.target.value)}
            style={{ padding: '6px 10px', border: '1px solid var(--line)', borderRadius: 8 }}>
            <option value="">全部状态</option>
            <option value="paid">已支付</option>
            <option value="pending">待支付</option>
            <option value="failed">失败</option>
          </select>
        </div>
      </div>
      <table className="board-table">
        <thead><tr><th>订单号</th><th>租户</th><th>套餐</th><th>渠道</th><th>金额</th><th>状态</th><th>创建时间</th><th>支付时间</th></tr></thead>
        <tbody>
          {shown.map(o => (
            <tr key={o.id}>
              <td>{o.id}</td>
              <td><b>{o.tenant_name}</b><small className="p-mono"> /b/{o.tenant_slug}</small></td>
              <td>{o.plan_code}</td><td>{o.channel}</td>
              <td>¥{Number(o.amount).toFixed(2)}</td>
              <td><span className={`st-${o.status === 'paid' ? 'ingested' : 'failed'}`}>
                {o.status === 'paid' ? '已支付' : o.status === 'pending' ? '待支付' : '失败'}</span></td>
              <td>{o.created_at}</td><td>{o.paid_at || '—'}</td>
            </tr>
          ))}
          {!shown.length && <tr><td colSpan={8} className="tadm-empty">暂无订单</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

/* ---------- 功能锁定面板(可见不可用,引导升级) ---------- */
const LOCK_DESC: Record<string, { desc: string; need: string }> = {
  docs: { desc: '知识域与知识库管理:创建知识域、上传课程资料,是 AI 顾问的知识基础。', need: '标准版' },
  ontology: { desc: '本体知识:班型/营期/费用等实体与规则的图谱化维护。', need: '标准版' },
  sessions: { desc: '对话记录:查看会话明细(脱敏)、按时间筛选、质检评分。', need: '旗舰版' },
  leads: { desc: '线索转化:报名意向工单跟进与状态管理。', need: '旗舰版' },
  analytics: { desc: '运营分析:高频问题、未答问题、趋势与 LLM 洞察。', need: '旗舰版' },
  usage: { desc: '用量统计:对话次数、活跃用户与近 14 日趋势图表。', need: '旗舰版' },
}

function LockPanel({ tabKey }: { tabKey: string }) {
  const info = LOCK_DESC[tabKey] || { desc: '该功能需升级套餐后使用。', need: '标准版' }
  return (
    <div className="tadm-lock">
      <h3>🔒 {info.need}功能</h3>
      <p>{info.desc}</p>
      <a href="#sub" onClick={e => {
        e.preventDefault()
        window.dispatchEvent(new CustomEvent('opc-goto-tab', { detail: 'sub' }))
      }}>升级套餐解锁 →</a>
    </div>
  )
}

/* ---------- 两套 Tab:平台经营(超管) / 业务工作(租户) ---------- */

const PLATFORM_TABS = [
  { key: 'tenants', label: '租户管理', desc: '机构租户 · 套餐 · 用量概览', el: <TenantsTab /> },
  { key: 'plans', label: '套餐定价', desc: '标准版 / 旗舰版 · 价格维护', el: <PlansTab /> },
  { key: 'orders', label: '订单管理', desc: '支付流水 · 状态核对', el: <OrdersTab /> },
  { key: 'board', label: '租户看板', desc: '租户级对话数 · 用户数 · 趋势图表', el: <BoardTab /> },
  { key: 'system', label: '系统设置', desc: '模型服务 · API Key · 渠道 · 全局参数', el: <SystemTab /> },
]

export default function Portal() {
  const [authed, setAuthed] = useState(!!localStorage.getItem(TOKEN_KEY))
  const [me, setMe] = useState<any>(null)              // /api/auth/me 身份
  const [tinfo, setTinfo] = useState<TenantInfo | null>(null)
  const [tinfoErr, setTinfoErr] = useState('')
  const [tab, setTab] = useState('')
  const isTenant = !!me?.user?.tenant_id && me.user.role !== 'superadmin'

  const loadTinfo = useCallback(() => {
    setTinfoErr('')
    api('/api/tenant/info').then(setTinfo)
      .catch(e => setTinfoErr(e.message === '401' ? '登录态已失效' : (e.message || '租户信息加载失败')))
  }, [])

  useEffect(() => {
    if (!authed) return
    api('/api/auth/me')
      .then(d => {
        setMe(d)
        if (d?.user?.tenant_id && d.user.role !== 'superadmin') {
          setTab('agents')   // 租户工作台默认智能体设置(免费版即可用)
          setTinfoErr('')
          api('/api/tenant/info').then(setTinfo)
            .catch(e => setTinfoErr(e.message === '401' ? '登录态已失效' : (e.message || '租户信息加载失败')))
        } else {
          setTab('tenants')
        }
      })
      .catch(() => { if (!localStorage.getItem(TOKEN_KEY)) setAuthed(false) })
  }, [authed])

  // 租户工作台:智能体设置与套餐订阅始终可用;其余 Tab 可见,按套餐功能位解锁
  const feats = tinfo?.features || tinfo?.subscription?.features || {}
  const unlocked = (f: string) => !!feats[f]
  const tenantTabs = tinfo ? [
    { key: 'institution', label: '机构信息', desc: '机构名称 · 统一服务宗旨', el: <TenantInstitutionTab info={tinfo} onChanged={loadTinfo} /> },
    { key: 'agents', label: '智能体设置', desc: '模型 · 能力 · 知识域 · 提示词', el: <TenantAgentTab info={tinfo} /> },
    { key: 'docs', label: '知识域', desc: '知识域 · 知识库 · 课程资料',
      el: unlocked('domains') ? <DomainsTab /> : <LockPanel tabKey="docs" /> },
    { key: 'ontology', label: '本体知识', desc: '实体 · 规则 · 关系',
      el: unlocked('ontology') ? <OntologyTab /> : <LockPanel tabKey="ontology" /> },
    { key: 'sessions', label: '对话记录', desc: '脱敏 · 时间筛选 · 质检',
      el: unlocked('sessions') ? <TenantSessionsTab /> : <LockPanel tabKey="sessions" /> },
    { key: 'leads', label: '线索转化', desc: '报名意向 · 留资工单',
      el: unlocked('leads') ? <LeadsTab /> : <LockPanel tabKey="leads" /> },
    { key: 'analytics', label: '运营分析', desc: '高频问题 · 未答 · 洞察',
      el: unlocked('analytics') ? <AnalyticsTab /> : <LockPanel tabKey="analytics" /> },
    { key: 'usage', label: '用量统计', desc: '对话次数 · 活跃用户 · 趋势',
      el: unlocked('analytics') ? <TenantStatsTab /> : <LockPanel tabKey="usage" /> },
    { key: 'sub', label: '套餐订阅', desc: '免费版 / 标准版 / 旗舰版', el: <TenantSubTab info={tinfo} onChanged={loadTinfo} /> },
  ] : []

  const tabs = isTenant ? tenantTabs : PLATFORM_TABS
  useEffect(() => {
    const h = (e: Event) => setTab((e as CustomEvent).detail)
    window.addEventListener('opc-goto-tab', h)
    return () => window.removeEventListener('opc-goto-tab', h)
  }, [])

  if (!authed) return <AuthPanel onOk={() => setAuthed(true)} />
  // 身份/租户信息加载完成前渲染占位,避免 tabs 为空导致渲染崩溃白屏
  if (isTenant && tinfoErr) {
    return (
      <div className="portal">
        <main className="p-main" style={{ padding: 40 }}>
          <div className="auth-error" style={{ maxWidth: 460 }}>{tinfoErr}</div>
          <button className="plan-cta" style={{ width: 'auto', padding: '9px 22px', marginTop: 12 }}
            onClick={() => { clearAuth(); setAuthed(false); setMe(null); setTinfo(null) }}>
            重新登录
          </button>
        </main>
      </div>
    )
  }
  if (!me || (isTenant && !tinfo)) {
    return <div className="portal"><main className="p-main" style={{ padding: 40 }}>加载中…</main></div>
  }
  const active = tabs.find(t => t.key === tab) || tabs[0]
  if (!active) return <div className="portal"><main className="p-main" style={{ padding: 40 }}>加载中…</main></div>
  const subActive = tinfo?.subscription?.status === 'active'
  return (
    <div className="portal">
      <aside className="p-side">
        <div className="p-brand">
          <img className="p-logo" src="/logo.png" alt="AI 课程顾问" />
          <div>
            <b>{isTenant ? (tinfo?.tenant?.name || '机构工作台') : 'SaaS 运营工作台'}</b>
            <small>{isTenant ? 'AI课程顾问管理工作台' : 'AI 教育顾问 · 平台经营'}</small>
          </div>
        </div>
        <nav className="p-nav" aria-label="管理功能">
          {tabs.map(t => (
            <button key={t.key} className={t.key === active.key ? 'on' : ''} onClick={() => setTab(t.key)}>
              <span className="ic">{NAV_ICONS[t.key]}</span>
              <span className="tx"><b>{t.label}</b><small>{t.desc}</small></span>
            </button>
          ))}
        </nav>
        <div className="p-side-foot">
          <button onClick={() => { clearAuth(); setAuthed(false); setMe(null) }}>退出登录</button>
        </div>
      </aside>

      <main className="p-main">
        {isTenant && !subActive && (
          <div className="quota-banner">
            <span>服务尚未开通:请选购套餐并完成支付,即可启用 AI 课程顾问与资料管理。</span>
            <a onClick={() => setTab('sub')} style={{ cursor: 'pointer' }}>去开通 →</a>
          </div>
        )}
        {isTenant && tinfo?.subscription?.plan_code === 'free' && (
          <div className="quota-banner" style={{ background: '#EFF6FF', borderColor: '#BFDBFE', color: '#1E40AF' }}>
            <span>当前为免费版:仅智能体设置可用。升级标准版解锁知识域与课程资料,让 Bot 基于你的课程资料作答。</span>
            <a onClick={() => setTab('sub')} style={{ cursor: 'pointer' }}>去升级 →</a>
          </div>
        )}
        <header className="p-pagehead">
          <h2>{active.label}</h2>
          <p>{active.desc}</p>
        </header>
        {active.el}
      </main>
    </div>
  )
}
