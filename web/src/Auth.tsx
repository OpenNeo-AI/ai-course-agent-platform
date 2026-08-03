/* SaaS 认证页(/login /register),参照 OpenNeo 手机验证码方案:
   - 注册:机构名 + 手机号 + 短信验证码(自动开通租户,登录走验证码)
   - 登录:手机验证码 或 账户密码(存量演示账户) */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { API, saveAuth } from './api'
import { useI18n } from './i18n'

const PHONE_RE = /^1[3-9]\d{9}$/

export default function Auth({ mode }: { mode: 'login' | 'register' }) {
  const nav = useNavigate()
  const { t } = useI18n()
  // 登录页默认验证码方式;注册页固定验证码
  const [method, setMethod] = useState<'sms' | 'password'>(mode === 'login' ? 'sms' : 'sms')
  const [orgName, setOrgName] = useState('')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [demoCode, setDemoCode] = useState('')     // 演示模式下后端回传的验证码
  const [countdown, setCountdown] = useState(0)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => () => { if (timer.current) clearInterval(timer.current) }, [])

  function afterAuth(d: any) {
    saveAuth(d.token, {
      username: d.user?.username, role: d.user?.role, tenant_id: d.user?.tenant_id,
      tenant_slug: d.tenant?.slug, tenant_name: d.tenant?.name,
    })
    nav('/portal')
  }

  async function sendCode() {
    setError(''); setDemoCode('')
    if (!PHONE_RE.test(phone)) { setError('请输入正确的手机号'); return }
    try {
      const res = await fetch(API + '/api/auth/sms/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || '发送失败')
      if (d.demo) setDemoCode(d.code)
      setCountdown(60)
      timer.current = setInterval(() => {
        setCountdown(c => {
          if (c <= 1 && timer.current) clearInterval(timer.current)
          return c - 1
        })
      }, 1000)
    } catch (e: any) { setError(e.message || '发送失败') }
  }

  async function submit() {
    if (busy) return
    setBusy(true); setError('')
    try {
      let path = '/api/auth/login'
      let body: Record<string, string> = {}
      if (mode === 'register') {
        if (!orgName.trim()) throw new Error('请填写机构名称')
        if (!code.trim()) throw new Error('请填写验证码')
        path = '/api/auth/sms/register'
        body = { org_name: orgName, phone, code }
      } else if (method === 'sms') {
        if (!code.trim()) throw new Error('请填写验证码')
        path = '/api/auth/sms/login'
        body = { phone, code }
      } else {
        path = '/api/auth/login'
        body = { username, password }
      }
      const res = await fetch(API + path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || `请求失败(${res.status})`)
      afterAuth(d)
    } catch (e: any) {
      setError(e.message || '操作失败,请重试')
    } finally { setBusy(false) }
  }

  const smsMode = mode === 'register' || method === 'sms'
  return (
    <div className="auth-page">
      <div className="auth-card">
        <Link to="/" className="auth-back">← {t('common.home')}</Link>
        <div className="auth-brand">
          <img src="/logo.png" alt="AI 教育顾问" />
          <b>AI 教育顾问 SaaS 平台</b>
        </div>
        <h1>{t(mode === 'register' ? 'auth.registerTitle' : 'auth.loginTitle')}</h1>
        <p className="auth-sub">{t(mode === 'register' ? 'auth.registerSub' : 'auth.loginSub')}</p>

        {mode === 'login' && (
          <div className="auth-tabs">
            <button className={method === 'sms' ? 'on' : ''} onClick={() => setMethod('sms')}>验证码登录</button>
            <button className={method === 'password' ? 'on' : ''} onClick={() => setMethod('password')}>密码登录</button>
          </div>
        )}

        {mode === 'register' && (
          <label className="auth-field">
            <span>{t('auth.orgName')}</span>
            <input value={orgName} onChange={e => setOrgName(e.target.value)}
              placeholder="例如:启明教育培训学校" maxLength={40} />
          </label>
        )}

        {smsMode ? (<>
          <label className="auth-field">
            <span>手机号</span>
            <input value={phone} onChange={e => setPhone(e.target.value.trim())}
              placeholder="用于接收验证码与登录" maxLength={11} />
          </label>
          <label className="auth-field">
            <span>短信验证码</span>
            <div className="auth-code-row">
              <input value={code} onChange={e => setCode(e.target.value.trim())}
                placeholder="6 位验证码" maxLength={6}
                onKeyDown={e => e.key === 'Enter' && submit()} />
              <button className="auth-code-btn" onClick={sendCode} disabled={countdown > 0}>
                {countdown > 0 ? `${countdown}s 后重发` : '获取验证码'}
              </button>
            </div>
          </label>
          {demoCode && (
            <div className="tadm-ok" style={{ marginBottom: 12 }}>
              演示环境(未接短信网关):本次验证码为 <b>{demoCode}</b>
            </div>
          )}
        </>) : (<>
          <label className="auth-field">
            <span>{t('auth.username')}</span>
            <input value={username} onChange={e => setUsername(e.target.value)}
              placeholder="请输入用户名" autoComplete="username" />
          </label>
          <label className="auth-field">
            <span>{t('auth.password')}</span>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
              placeholder="请输入密码" autoComplete="current-password"
              onKeyDown={e => e.key === 'Enter' && submit()} />
          </label>
        </>)}

        {error && <div className="auth-error">{error}</div>}
        <button className="auth-submit" onClick={submit} disabled={busy}>
          {busy ? t('common.loading')
            : mode === 'register' ? t('auth.submitRegister') : t('auth.submitLogin')}
        </button>

        <div className="auth-switch">
          {mode === 'register'
            ? <>{t('auth.hasAccount')}<Link to="/login">{t('common.login')}</Link></>
            : <>{t('auth.noAccount')}<Link to="/register">{t('pricing.freeCta')}</Link></>}
        </div>
        {mode === 'login' && method === 'password' && (
          <div className="auth-demo">演示账号:平台超管 demo / demo1234 · 演示租户 demo-org / demo1234</div>
        )}
      </div>
    </div>
  )
}
