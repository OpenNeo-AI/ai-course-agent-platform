/* SaaS 登录 / 租户注册页(/login /register)。
   注册=机构自助开通:建租户+管理员+知识库+免费订阅,成功后直达管理后台。 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { API, saveAuth } from './api'
import { useI18n } from './i18n'

export default function Auth({ mode }: { mode: 'login' | 'register' }) {
  const nav = useNavigate()
  const { t } = useI18n()
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
        <Link to="/" className="auth-back">← {t('common.home')}</Link>
        <div className="auth-brand">
          <img src="/logo.png" alt="AI 教育顾问" />
          <b>AI 教育顾问 SaaS 平台</b>
        </div>
        <h1>{t(mode === 'register' ? 'auth.registerTitle' : 'auth.loginTitle')}</h1>
        <p className="auth-sub">
          {t(mode === 'register' ? 'auth.registerSub' : 'auth.loginSub')}
        </p>

        {mode === 'register' && (
          <label className="auth-field">
            <span>{t('auth.orgName')}</span>
            <input value={orgName} onChange={e => setOrgName(e.target.value)}
              placeholder="例如:启明教育培训学校" maxLength={40} />
          </label>
        )}
        <label className="auth-field">
          <span>{t('auth.username')}</span>
          <input value={username} onChange={e => setUsername(e.target.value)}
            placeholder="3-24 位字母/数字/下划线" autoComplete="username" />
        </label>
        <label className="auth-field">
          <span>{t('auth.password')}</span>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder={mode === 'register' ? '至少 6 位' : '请输入密码'}
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            onKeyDown={e => e.key === 'Enter' && submit()} />
        </label>

        {error && <div className="auth-error">{error}</div>}
        <button className="auth-submit" onClick={submit} disabled={busy}>
          {busy ? t('common.loading') : t(mode === 'register' ? 'auth.submitRegister' : 'auth.submitLogin')}
        </button>

        <div className="auth-switch">
          {mode === 'register'
            ? <>{t('auth.hasAccount')}<Link to="/login">{t('common.login')}</Link></>
            : <>{t('auth.noAccount')}<Link to="/register">{t('pricing.freeCta')}</Link></>}
        </div>
        {mode === 'login' && (
          <div className="auth-demo">演示账号:平台超管 demo / demo1234 · 演示租户 demo-org / demo1234</div>
        )}
      </div>
    </div>
  )
}
