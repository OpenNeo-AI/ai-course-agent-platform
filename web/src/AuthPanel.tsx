/* 统一认证面板:横版布局 + 多页签(验证码登录 / 密码登录 / 注册开通)。
   /portal 未登录时内嵌展示;/login 与 /register 以 initialTab 预选页签。
   注册=机构名+手机号+验证码,开通免费版租户;验证码登录仅已注册手机号。 */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { API, saveAuth } from './api'
import { LangSwitch, useI18n } from './i18n'

export type AuthTab = 'sms' | 'password' | 'register'

const PHONE_RE = /^1[3-9]\d{9}$/
const USER_RE = /^[A-Za-z0-9_-]{3,24}$/

export default function AuthPanel({ initialTab = 'sms', onOk, standalone = false }: {
  initialTab?: AuthTab
  onOk?: () => void            // /portal 内嵌:登录成功回调(不再跳转)
  standalone?: boolean         // 独立页(/login /register):登录成功跳转 /portal
}) {
  const { t } = useI18n()
  const nav = useNavigate()
  const [tab, setTab] = useState<AuthTab>(initialTab)
  const [orgName, setOrgName] = useState('')
  const [regUser, setRegUser] = useState('')     // 注册页签:账户名
  const [regPass, setRegPass] = useState('')     // 注册页签:密码
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [username, setUsername] = useState('')   // 密码登录页签:账户名或手机号
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [demoCode, setDemoCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => () => { if (timer.current) clearInterval(timer.current) }, [])

  function afterAuth(d: any) {
    saveAuth(d.token, {
      username: d.user?.username, role: d.user?.role, tenant_id: d.user?.tenant_id,
      tenant_slug: d.tenant?.slug, tenant_name: d.tenant?.name,
    })
    if (onOk) { onOk(); return }
    nav('/portal')
  }

  async function sendCode() {
    setError(''); setDemoCode('')
    if (!PHONE_RE.test(phone)) { setError(t('auth.errPhone')); return }
    try {
      const res = await fetch(API + '/api/auth/sms/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || t('auth.errSendFail'))
      if (d.demo) setDemoCode(d.code)
      setCountdown(60)
      timer.current = setInterval(() => {
        setCountdown(c => {
          if (c <= 1 && timer.current) clearInterval(timer.current)
          return c - 1
        })
      }, 1000)
    } catch (e: any) { setError(e.message || t('auth.errSendFail')) }
  }

  async function submit() {
    if (busy) return
    setBusy(true); setError('')
    try {
      let path = '/api/auth/login'
      let body: Record<string, string> = {}
      if (tab === 'register') {
        if (!orgName.trim()) throw new Error(t('auth.errOrgName'))
        if (!USER_RE.test(regUser.trim())) throw new Error(t('auth.errUser'))
        if (!regPass || regPass.length < 6) throw new Error(t('auth.errPass'))
        if (!PHONE_RE.test(phone)) throw new Error(t('auth.errPhone'))
        if (!code.trim()) throw new Error(t('auth.errCode'))
        path = '/api/auth/sms/register'
        body = { org_name: orgName, username: regUser.trim(), password: regPass, phone, code }
      } else if (tab === 'sms') {
        if (!PHONE_RE.test(phone)) throw new Error(t('auth.errPhone'))
        if (!code.trim()) throw new Error(t('auth.errCode'))
        path = '/api/auth/sms/login'
        body = { phone, code }
      } else {
        if (!username.trim() || !password) throw new Error(t('auth.errAccountPass'))
        body = { username: username.trim(), password }
      }
      const res = await fetch(API + path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || `${t('auth.errReqFail')}(${res.status})`)
      afterAuth(d)
    } catch (e: any) {
      setError(e.message || t('auth.errFallback'))
    } finally { setBusy(false) }
  }

  const TABS: { key: AuthTab; label: string }[] = [
    { key: 'sms', label: t('auth.tabSms') },
    { key: 'password', label: t('auth.tabPassword') },
    { key: 'register', label: t('auth.tabRegister') },
  ]

  return (
    <div className="aw-page">
      <div className="aw-card">
        <aside className="aw-brand">
          <div className="aw-brand-top">
            <img src="/logo.png" alt={t('auth.brandAlt')} />
            <b>{t('auth.brandTitle')}</b>
          </div>
          <h2>{t('auth.headline1')}<br />{t('auth.headline2')}</h2>
          <ul>
            <li>{t('auth.feat1')}</li>
            <li>{t('auth.feat2')}</li>
            <li>{t('auth.feat3')}</li>
          </ul>
          <div className="aw-brand-demo">
            {t('auth.demoLabel')}<br />
            {t('auth.demoList')}
          </div>
        </aside>

        <div className="aw-form">
          <div style={{ position: 'absolute', top: 16, right: 20, display: 'flex', gap: 12, alignItems: 'center' }}>
            {standalone && <Link to="/" className="aw-back" style={{ position: 'static' }}>{t('auth.backHome')}</Link>}
            <LangSwitch />
          </div>
          <div className="aw-tabs">
            {TABS.map(tb => (
              <button key={tb.key} className={tab === tb.key ? 'on' : ''}
                onClick={() => { setTab(tb.key); setError('') }}>{tb.label}</button>
            ))}
          </div>

          {tab === 'register' && (<>
            <label className="aw-field">
              <span>{t('auth.orgName')}</span>
              <input value={orgName} onChange={e => setOrgName(e.target.value)}
                placeholder={t('auth.phOrgName')} maxLength={40} />
            </label>
            <label className="aw-field">
              <span>{t('auth.fAccount')}</span>
              <input value={regUser} onChange={e => setRegUser(e.target.value.trim())}
                placeholder={t('auth.phAccount')} maxLength={24}
                autoComplete="username" />
            </label>
            <label className="aw-field">
              <span>{t('auth.password')}</span>
              <input type="password" value={regPass} onChange={e => setRegPass(e.target.value)}
                placeholder={t('auth.phPasswordReg')} autoComplete="new-password" />
            </label>
          </>)}

          {tab !== 'password' ? (<>
            <label className="aw-field">
              <span>{t('auth.fPhone')}</span>
              <input value={phone} onChange={e => setPhone(e.target.value.trim())}
                placeholder={tab === 'register' ? t('auth.phPhoneReg') : t('auth.phPhoneLogin')}
                maxLength={11} />
            </label>
            <label className="aw-field">
              <span>{t('auth.fCode')}</span>
              <div className="aw-code-row">
                <input value={code} onChange={e => setCode(e.target.value.trim())}
                  placeholder={t('auth.phCode')} maxLength={6}
                  onKeyDown={e => e.key === 'Enter' && submit()} />
                <button type="button" className="aw-code-btn" onClick={sendCode}
                  disabled={countdown > 0}>
                  {countdown > 0 ? `${countdown}${t('auth.resend')}` : t('auth.getCode')}
                </button>
              </div>
            </label>
            {demoCode && (
              <div className="aw-demo-code">
                {t('auth.demoCodeNote')} <b>{demoCode}</b>
              </div>
            )}
          </>) : (<>
            <label className="aw-field">
              <span>{t('auth.fAccountShort')}</span>
              <input value={username} onChange={e => setUsername(e.target.value.trim())}
                placeholder={t('auth.phAccountLogin')} autoComplete="username" />
            </label>
            <label className="aw-field">
              <span>{t('auth.password')}</span>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                placeholder={t('auth.phPasswordLogin')} autoComplete="current-password"
                onKeyDown={e => e.key === 'Enter' && submit()} />
            </label>
          </>)}

          {error && <div className="aw-error">{error}</div>}
          <button className="aw-submit" onClick={submit} disabled={busy}>
            {busy ? t('auth.processing')
              : tab === 'register' ? t('auth.submitRegisterFree')
                : t('auth.submitLogin')}
          </button>
          <p className="aw-hint">
            {tab === 'register'
              ? t('auth.hintRegister')
              : tab === 'sms' ? t('auth.hintSms')
                : t('auth.hintPassword')}
          </p>
        </div>
      </div>
    </div>
  )
}
