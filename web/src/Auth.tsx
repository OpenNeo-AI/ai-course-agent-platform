/* SaaS 登录 / 租户注册页(/login /register)。
   注册=机构自助开通:建租户+管理员+知识库+免费订阅,成功后直达管理后台。 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { API, saveAuth } from './api'

export default function Auth({ mode }: { mode: 'login' | 'register' }) {
  const nav = useNavigate()
  const [orgName, setOrgName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const path = mode === 'register' ? '/api/auth/register' : '/api/auth/login'
      const body = mode === 'register'
        ? { org_name: orgName, username, password }
        : { username, password }
      const res = await fetch(API + path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || `请求失败(${res.status})`)
      saveAuth(d.token, {
        username: d.user?.username, role: d.user?.role, tenant_id: d.user?.tenant_id,
        tenant_slug: d.tenant?.slug, tenant_name: d.tenant?.name,
      })
      nav(d.user?.role === 'superadmin' ? '/portal' : '/admin')
    } catch (e: any) {
      setError(e.message || '操作失败,请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <Link to="/" className="auth-back">← 返回首页</Link>
        <div className="auth-brand">
          <img src="/logo.png" alt="AI 教育顾问" />
          <b>AI 教育顾问 SaaS 平台</b>
        </div>
        <h1>{mode === 'register' ? '开通机构账号' : '登录'}</h1>
        <p className="auth-sub">
          {mode === 'register'
            ? '注册即开通:专属知识库 + 免费版每月 50 次 AI 对话'
            : '机构管理员或平台管理员登录'}
        </p>

        {mode === 'register' && (
          <label className="auth-field">
            <span>机构名称</span>
            <input value={orgName} onChange={e => setOrgName(e.target.value)}
              placeholder="例如:启明教育培训学校" maxLength={40} />
          </label>
        )}
        <label className="auth-field">
          <span>用户名</span>
          <input value={username} onChange={e => setUsername(e.target.value)}
            placeholder="3-24 位字母/数字/下划线" autoComplete="username" />
        </label>
        <label className="auth-field">
          <span>密码</span>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder={mode === 'register' ? '至少 6 位' : '请输入密码'}
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            onKeyDown={e => e.key === 'Enter' && submit()} />
        </label>

        {error && <div className="auth-error">{error}</div>}
        <button className="auth-submit" onClick={submit} disabled={busy}>
          {busy ? '处理中…' : (mode === 'register' ? '注册并开通' : '登录')}
        </button>

        <div className="auth-switch">
          {mode === 'register'
            ? <>已有账号?<Link to="/login">直接登录</Link></>
            : <>还没有账号?<Link to="/register">免费注册开通</Link></>}
        </div>
        {mode === 'login' && (
          <div className="auth-demo">演示账号:平台超管 demo / demo1234 · 演示租户 demo-org / demo1234</div>
        )}
      </div>
    </div>
  )
}
